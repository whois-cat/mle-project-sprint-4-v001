import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import pyarrow.dataset as ds
import redis.asyncio as redis
from fastapi import FastAPI, Header, HTTPException, Request, Body
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import Response as StarletteResponse

from config import CFG
from settings import ServiceSettings, get_settings


logging.basicConfig(
    level=CFG.LOG_LEVEL,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("recsys")
settings = get_settings()
limiter = Limiter(key_func=get_remote_address)

HTTP_REQ = Counter("http_requests_total", "Total HTTP requests", ["method", "path", "status"])
HTTP_LAT = Histogram("http_request_latency_seconds", "Request latency", ["path"])
RECS_SRC = Counter("recs_source_total", "Returned recommendations by source", ["source"])
RECS_EMPTY = Counter("recs_empty_total", "Recommend returned empty list")


DATASETS: dict[str, tuple[str, list[str]]] = {
    "ranked_ds": ("ranked", ["user_id", "track_id", "rank", "score"]),
    "personal_ds": ("personal_als", ["user_id", "track_id", "rank", "score"]),
    "similar_ds": ("similar", ["track_id", "similar_track_id", "rank", "score"]),
    "popular_ds": ("top_popular", ["track_id"]),
}


class RecRequest(BaseModel):
    user_id: int
    online_tracks: list[int] | None = None


class RecResponse(BaseModel):
    track_id: int
    rank: int
    score: float
    source: str

@dataclass
class AppState:
    settings: ServiceSettings
    redis_client: redis.Redis | None = None
    online_fallback: dict[int, list[int]] = field(default_factory=dict)

    ranked_ds: ds.Dataset | None = None
    personal_ds: ds.Dataset | None = None
    similar_ds: ds.Dataset | None = None
    popular_ds: ds.Dataset | None = None

    get_offline_user_recs: Any = None
    get_similar: Any = None
    get_popular_pool: Any = None

    @property
    def offline_ready(self) -> bool:
        return self.ranked_ds is not None and self.personal_ds is not None


def ensure_columns(dataset: ds.Dataset, required: list[str]) -> None:
    missing = [c for c in required if c not in dataset.schema.names]
    if missing:
        raise ValueError(f"dataset missing columns: {missing}")


def load_dataset(key: str) -> ds.Dataset | None:
    path = CFG.ARTIFACTS_DIR / CFG.RECS_FILES[key]
    return ds.dataset(str(path), format="parquet") if path.exists() else None


def stable_unique(values: list[int]) -> list[int]:
    return list(dict.fromkeys(map(int, values)))


def normalize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []
    mn = min(float(r["score"]) for r in records)
    mx = max(float(r["score"]) for r in records)
    if mx <= mn:
        return [{**r, "norm": 1.0} for r in records]
    d = mx - mn
    return [{**r, "norm": (float(r["score"]) - mn) / d} for r in records]


def upd(cands: dict[int, dict[str, Any]], track_id: int, score: float, source: str) -> None:
    prev = cands.get(track_id)
    if prev is None or score > float(prev["score"]):
        cands[track_id] = {"track_id": int(track_id), "score": float(score), "source": source}


def attach_cached_accessors(state: AppState) -> None:
    topn = int(state.settings.service_cache_topn)
    similar_per_track = min(30, int(CFG.SIMILAR_TOP_N))
    max_popular = max(int(CFG.TOP_K) * int(state.settings.popular_pool_multiplier), int(state.settings.popular_pool_min))

    @lru_cache(maxsize=50_000)
    def offline(source: str, user_id: int) -> list[dict[str, Any]]:
        dataset = state.ranked_ds if source == "ranked" else state.personal_ds
        if dataset is None:
            return []
        table = dataset.to_table(filter=ds.field("user_id") == int(user_id), columns=["track_id", "rank", "score"])
        if table.num_rows == 0:
            return []
        ranks = table["rank"].to_numpy(zero_copy_only=False)
        order = ranks.argsort(kind="stable")[:topn]
        ids = table["track_id"].to_numpy(zero_copy_only=False)[order]
        sc = table["score"].to_numpy(zero_copy_only=False)[order]
        rk = ranks[order]
        return [{"track_id": int(ids[i]), "rank": int(rk[i]), "score": float(sc[i])} for i in range(len(order))]

    @lru_cache(maxsize=100_000)
    def similar(track_id: int) -> list[dict[str, Any]]:
        if state.similar_ds is None:
            return []
        table = state.similar_ds.to_table(
            filter=ds.field("track_id") == int(track_id),
            columns=["similar_track_id", "rank", "score"],
        )
        if table.num_rows == 0:
            return []
        ranks = table["rank"].to_numpy(zero_copy_only=False)
        order = ranks.argsort(kind="stable")[:similar_per_track]
        ids = table["similar_track_id"].to_numpy(zero_copy_only=False)[order]
        sc = table["score"].to_numpy(zero_copy_only=False)[order]
        return [{"track_id": int(ids[i]), "score": float(sc[i])} for i in range(len(order))]

    @lru_cache(maxsize=1)
    def popular_pool() -> list[int]:
        if state.popular_ds is None:
            return []
        table = state.popular_ds.to_table(columns=["track_id"])
        if table.num_rows == 0:
            return []
        ids = table["track_id"].to_numpy(zero_copy_only=False)[:max_popular]
        return [int(x) for x in ids]

    state.get_offline_user_recs = offline
    state.get_similar = similar
    state.get_popular_pool = popular_pool


def load_all_datasets(state: AppState) -> None:
    for attr, (key, cols) in DATASETS.items():
        dataset = load_dataset(key)
        if dataset is not None:
            ensure_columns(dataset, cols)
        setattr(state, attr, dataset)
    attach_cached_accessors(state)


async def add_online(state: AppState, user_id: int, tracks: list[int]) -> None:
    if not tracks:
        return
    normalized = [int(x) for x in tracks]
    if state.redis_client is not None:
        key = f"online:{int(user_id)}"
        try:
            async with asyncio.timeout(float(state.settings.redis_timeout_seconds)):
                await state.redis_client.lpush(key, *map(str, normalized))
                await state.redis_client.ltrim(key, 0, int(state.settings.online_keep) - 1)
                if int(state.settings.cache_ttl_seconds) > 0:
                    await state.redis_client.expire(key, int(state.settings.cache_ttl_seconds))
            return
        except Exception as e:
            logger.warning("redis write failed: %s", e)

    prev = state.online_fallback.get(int(user_id), [])
    state.online_fallback[int(user_id)] = (normalized + prev)[: int(state.settings.online_keep)]


async def get_online(state: AppState, user_id: int) -> list[int]:
    if state.redis_client is not None:
        key = f"online:{int(user_id)}"
        try:
            async with asyncio.timeout(float(state.settings.redis_timeout_seconds)):
                values = await state.redis_client.lrange(key, 0, int(state.settings.online_keep) - 1)
            return [int(x) for x in values]
        except Exception as e:
            logger.warning("redis read failed: %s", e)
    return state.online_fallback.get(int(user_id), [])


@asynccontextmanager
async def lifespan(app: FastAPI):
    state = AppState(settings=settings)
    app.state.state = state

    if state.settings.redis_url:
        try:
            state.redis_client = redis.from_url(state.settings.redis_url, decode_responses=True)
            await state.redis_client.ping()
            logger.info("redis connected")
        except Exception as e:
            logger.warning("redis unavailable: %s", e)
            state.redis_client = None

    load_all_datasets(state)

    logger.info(
        "ready: offline=%s similar=%s popular=%s cache_topn=%d online_take=%d",
        state.offline_ready,
        state.similar_ds is not None,
        state.popular_ds is not None,
        int(state.settings.service_cache_topn),
        int(state.settings.online_take),
    )

    yield

    if state.redis_client is not None:
        await state.redis_client.close()
        logger.info("redis closed")


app = FastAPI(title="music rec service", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, lambda _r, _e: StarletteResponse("rate limit exceeded", status_code=429))


@app.middleware("http")
async def metrics_mw(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        resp = await call_next(request)
        status = resp.status_code
        return resp
    finally:
        path = request.url.path
        HTTP_REQ.labels(request.method, path, str(status)).inc()
        HTTP_LAT.labels(path).observe(time.perf_counter() - start)


@app.get("/health")
async def health(request: Request):
    st: AppState = request.app.state.state
    return {
        "status": "ok" if st.offline_ready else "degraded",
        "offline": st.offline_ready,
        "similar": st.similar_ds is not None,
        "popular": st.popular_ds is not None,
        "redis": bool(st.redis_client),
    }


app.add_api_route(settings.metrics_path, lambda _r: StarletteResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST), methods=["GET"])


@app.post("/reload")
async def reload(request: Request, x_reload_token: str | None = Header(default=None)):
    st: AppState = request.app.state.state
    if st.settings.reload_token and x_reload_token != st.settings.reload_token:
        raise HTTPException(403, "forbidden")
    load_all_datasets(st)
    logger.info("reload ok: offline=%s similar=%s popular=%s", st.offline_ready, st.similar_ds is not None, st.popular_ds is not None)
    return {"status": "reloaded", "offline": st.offline_ready, "similar": st.similar_ds is not None, "popular": st.popular_ds is not None}


@app.post("/recommend", response_model=list[RecResponse])
@limiter.limit(settings.recommend_rate_limit)
async def recommend(request: Request, req: RecRequest = Body(...)):
    st: AppState = request.app.state.state
    if not st.offline_ready:
        raise HTTPException(503, "offline datasets are not available")

    user_id = int(req.user_id)
    incoming = [int(x) for x in (req.online_tracks or [])]

    await add_online(st, user_id, incoming)
    history = await get_online(st, user_id)

    context = stable_unique(incoming + history)[: int(st.settings.online_history_take)]
    context_set = set(context)

    ranked = normalize(st.get_offline_user_recs("ranked", user_id))
    personal = normalize(st.get_offline_user_recs("personal", user_id))

    similar_max: dict[int, float] = {}
    if st.similar_ds is not None and context and int(st.settings.online_take) > 0:
        for tid in context:
            for cand in st.get_similar(int(tid)):
                cid = int(cand["track_id"])
                if cid in context_set:
                    continue
                sc = float(cand["score"])
                prev = similar_max.get(cid)
                if prev is None or sc > prev:
                    similar_max[cid] = sc

    sim = normalize([{"track_id": k, "score": v} for k, v in similar_max.items()])
    sim.sort(key=lambda x: float(x["norm"]), reverse=True)

    top_k = int(CFG.TOP_K)
    cands: dict[int, dict[str, Any]] = {}

    for r in ranked[:top_k]:
        upd(cands, int(r["track_id"]), float(r["norm"]) * float(st.settings.weight_ranked), "ranked")
    for r in sim[: int(st.settings.online_take)]:
        upd(cands, int(r["track_id"]), float(r["norm"]) * float(st.settings.weight_similar_online), "similar_online")
    for r in personal[:top_k]:
        upd(cands, int(r["track_id"]), float(r["norm"]) * float(st.settings.weight_personal), "personal")

    if len(cands) < top_k and st.popular_ds is not None:
        for tid in st.get_popular_pool():
            if tid in context_set:
                continue
            upd(cands, int(tid), 1.0 * float(st.settings.weight_popular), "popular")
            if len(cands) >= top_k * 5:
                break

    if not cands:
        RECS_EMPTY.inc()
        return []

    out = sorted(cands.values(), key=lambda x: float(x["score"]), reverse=True)[:top_k]
    res = [RecResponse(track_id=int(x["track_id"]), rank=i + 1, score=float(x["score"]), source=str(x["source"])) for i, x in enumerate(out)]
    for r in res:
        RECS_SRC.labels(r.source).inc()
    return res
