from __future__ import annotations

import logging
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

import recommendations_service


logger = logging.getLogger("service_tests")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("recsys").setLevel(logging.WARNING)


def make_recs(*, base_track_id: int, n: int, score_start: float) -> list[dict[str, Any]]:
    return [
        {"track_id": int(base_track_id + i), "rank": i + 1, "score": float(score_start - i * 0.05)}
        for i in range(int(n))
    ]


def log_recs(case: str, user_id: int, recs: list[dict[str, Any]]) -> None:
    sources = Counter(str(x.get("source")) for x in recs)
    top_k = min(int(recommendations_service.CFG.TOP_K), len(recs))
    head = [(int(x["track_id"]), str(x.get("source"))) for x in recs[:top_k] if "track_id" in x]
    
    logger.info(
        "%s | user_id=%d | n=%d | sources=%s | head=%s",
        case, user_id, len(recs), dict(sources), head,
    )


def has_source(recs: list[dict[str, Any]], source: str) -> bool:
    return any(str(x.get("source")) == source for x in recs)


async def recommend(client: httpx.AsyncClient, user_id: int, online_tracks: list[int] | None = None) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"user_id": int(user_id)}
    if online_tracks:
        payload["online_tracks"] = [int(x) for x in online_tracks]

    response = await client.post("/recommend", json=payload)
    assert response.status_code == 200, response.text

    data = response.json()
    assert isinstance(data, list)
    return [x for x in data if isinstance(x, dict)]


@pytest.fixture()
def patch_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recommendations_service.settings, "redis_url", None, raising=False)

    def fake_load_all_datasets(state: Any) -> None:
        state.ranked_ds = state.personal_ds = state.similar_ds = state.popular_ds = object()

        top_k = int(recommendations_service.CFG.TOP_K)

        def offline(source: str, user_id: int) -> list[dict[str, Any]]:
            user_id_int = int(user_id)

            if source == "ranked":
                ranked_take = max(1, top_k - 3)
                return make_recs(base_track_id=200_000 + user_id_int * 1_000, n=ranked_take, score_start=0.9)

            if source == "personal":
                if user_id_int == 1:
                    return []
                return make_recs(base_track_id=400_000 + user_id_int * 1_000, n=3, score_start=0.95)

            return []

        def similar(track_id: int) -> list[dict[str, Any]]:
            return [{"track_id": 999, "score": 1.0}] if int(track_id) == 101 else []

        def popular_pool() -> list[int]:
            return list(range(501, 501 + top_k * 20))

        state.get_offline_user_recs = offline
        state.get_similar = similar
        state.get_popular_pool = popular_pool

    monkeypatch.setattr(recommendations_service, "load_all_datasets", fake_load_all_datasets, raising=True)


@pytest.fixture()
async def client(patch_service) -> AsyncIterator[httpx.AsyncClient]:
    async with recommendations_service.lifespan(recommendations_service.app):
        transport = httpx.ASGITransport(app=recommendations_service.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client


@pytest.mark.asyncio
async def test_user_without_personal(client: httpx.AsyncClient) -> None:
    recs = await recommend(client, user_id=1)
    log_recs("CASE1 | without personal recommendations", 1, recs)

    expected_top_k = int(recommendations_service.CFG.TOP_K)
    assert len(recs) == expected_top_k
    assert not has_source(recs, "personal")


@pytest.mark.asyncio
async def test_user_with_personal_no_online_history(client: httpx.AsyncClient) -> None:
    recs = await recommend(client, user_id=2)
    log_recs("CASE2 | personal recommendations without history", 2, recs)

    expected_top_k = int(recommendations_service.CFG.TOP_K)
    assert len(recs) == expected_top_k
    assert has_source(recs, "personal")
    assert not has_source(recs, "similar_online")


@pytest.mark.asyncio
async def test_user_with_personal_and_online_history(client: httpx.AsyncClient) -> None:
    await recommend(client, user_id=2, online_tracks=[101])
    recs = await recommend(client, user_id=2)
    log_recs("CASE3 | personal recommendations with history", 2, recs)

    expected_top_k = int(recommendations_service.CFG.TOP_K)
    assert len(recs) == expected_top_k
    assert has_source(recs, "similar_online")
