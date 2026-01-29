from __future__ import annotations

import os
import json
import time
import urllib.error
import urllib.request
from typing import Any

import click
import pyarrow.dataset as ds

from config import CFG


def http_json(method: str, base_url: str, path: str, payload: dict[str, Any] | None, timeout: float) -> Any:
    url = f"{base_url}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if payload is None else {"Content-Type": "application/json"}
    req = urllib.request.Request(url=url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise click.ClickException(f"{method.lower()} {path} failed: http={exc.code} body={raw}") from exc


def pick_user_ids(*, take: int) -> list[int]:
    if not CFG.RECS_FILES["ranked"].exists():
        raise FileNotFoundError(f"ranked parquet not found: {CFG.RECS_FILES['ranked'].as_posix()}")

    dataset = ds.dataset(str(CFG.RECS_FILES["ranked"]), format="parquet")
    if "user_id" not in dataset.schema.names:
        raise ValueError(f"ranked parquet has no user_id column, only columns={dataset.schema.names}")

    out: list[int] = []
    seen: set[int] = set()

    for batch in dataset.scanner(columns=["user_id"], batch_size=200_000).to_batches():
        for value in batch.column(0).to_numpy(zero_copy_only=False):
            if value is None:
                continue
            user_id = int(value)
            if user_id in seen:
                continue
            seen.add(user_id)
            out.append(user_id)
            if len(out) >= take:
                return out

    return out


def sources_have_similar(recs: Any) -> bool:
    if not isinstance(recs, list):
        return False
    return any(isinstance(x, dict) and x.get("source") == "similar_online" for x in recs)


def take_seeds(recs: Any, *, seed_take: int) -> list[int]:
    if not isinstance(recs, list) or seed_take <= 0:
        return []
    out: list[int] = []
    for item in recs[:seed_take]:
        if isinstance(item, dict) and "track_id" in item:
            out.append(int(item["track_id"]))
    return out


@click.command()
@click.option("--users", "users_take", default=20, show_default=True, type=int)
@click.option("--rounds", default=3, show_default=True, type=int)
@click.option("--seed-take", default=5, show_default=True, type=int)
@click.option("--sleep", "sleep_seconds", default=0.2, show_default=True, type=float)
@click.option("--timeout", "timeout_seconds", default=5.0, show_default=True, type=float)
def main(users_take: int, rounds: int, seed_take: int, sleep_seconds: float, timeout_seconds: float) -> None:
    host, port = os.getenv("APP_HOST", "0.0.0.0"), int(os.getenv("APP_PORT", "8000"))
    base_url = f"http://{host}:{port}"
    user_ids = pick_user_ids(take=users_take)
    if not user_ids:
        raise click.ClickException("no user ids found in ranked parquet")

    warmed: list[int] = []
    with_similar: list[int] = []

    for user_id in user_ids:
        seeds: list[int] = []
        wrote_online = False
        saw_similar = False

        for _ in range(max(1, rounds)):
            payload: dict[str, Any] = {"user_id": int(user_id)}
            if seeds:
                payload["online_tracks"] = seeds
                wrote_online = True

            recs = http_json("POST", base_url, "/recommend", payload, timeout_seconds)
            saw_similar = saw_similar or sources_have_similar(recs)

            seeds = take_seeds(recs, seed_take=seed_take)
            if not seeds:
                break

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        if wrote_online:
            warmed.append(int(user_id))
        if saw_similar:
            with_similar.append(int(user_id))

    CFG.SERVICE_FILES["warmed_users"].write_text(
        json.dumps(
            {"picked_user_ids": user_ids, "warmed_user_ids": warmed, "users_with_similar": with_similar},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    click.echo(f"picked={len(user_ids)} warmed={len(warmed)} with_similar={len(with_similar)}")
    click.echo(f"saved={CFG.SERVICE_FILES['warmed_users'].as_posix()}")


if __name__ == "__main__":
    main()
