"""Запись в Supabase через REST (PostgREST) service-ключом."""
from datetime import datetime, timezone

import requests

from . import config

CHUNK = 500


def _headers(prefer: str | None = None) -> dict:
    h = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if prefer:
        h["Prefer"] = prefer
    return h


def _url(table: str) -> str:
    return f"{config.SUPABASE_URL}/rest/v1/{table}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert(table: str, rows: list[dict], on_conflict: str, ignore_duplicates: bool = False) -> None:
    """Пакетный upsert. ignore_duplicates=True — существующие строки не трогаем."""
    if not rows:
        return
    resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
    for i in range(0, len(rows), CHUNK):
        resp = requests.post(
            _url(table),
            params={"on_conflict": on_conflict},
            headers=_headers(f"resolution={resolution},return=minimal"),
            json=rows[i:i + CHUNK],
            timeout=60,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase {table}: {resp.status_code} {resp.text[:500]}")


def insert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    for i in range(0, len(rows), CHUNK):
        resp = requests.post(
            _url(table), headers=_headers("return=minimal"), json=rows[i:i + CHUNK], timeout=60,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Supabase {table}: {resp.status_code} {resp.text[:500]}")


def select(table: str, params: dict) -> list[dict]:
    resp = requests.get(_url(table), headers=_headers(), params=params, timeout=60)
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase {table}: {resp.status_code} {resp.text[:500]}")
    return resp.json()


def update(table: str, match: dict, values: dict) -> None:
    resp = requests.patch(
        _url(table), headers=_headers("return=minimal"), params=match, json=values, timeout=60,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Supabase {table}: {resp.status_code} {resp.text[:500]}")


def save_reels(reels: list[dict]) -> None:
    """Обновляет reels и пишет снимок просмотров для расчёта скорости роста."""
    if not reels:
        return
    by_code = {r["short_code"]: r for r in reels}   # дубли внутри пачки → последний
    rows = [{**r, "updated_at": now_iso()} for r in by_code.values()]
    upsert("reels", rows, on_conflict="short_code")
    stamp = now_iso()
    insert("reel_snapshots", [
        {"short_code": r["short_code"], "captured_at": stamp,
         "views": r["views"], "likes": r["likes"], "comments": r["comments"]}
        for r in by_code.values()
    ])
