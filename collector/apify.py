"""Минимальный клиент Apify API: запустить Actor, дождаться, забрать результаты."""
import time

import requests

from . import config

API = "https://api.apify.com/v2"


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.APIFY_TOKEN}"}


def run_actor(actor_id: str, run_input: dict, max_items: int) -> list[dict]:
    """Запускает Actor и возвращает элементы его датасета.

    max_items и maxTotalChargeUsd — ограничители: Actor не соберёт и не спишет больше.
    """
    actor_path = actor_id.replace("/", "~")
    params = {
        "maxItems": max_items,
        "maxTotalChargeUsd": config.MAX_CHARGE_PER_RUN_USD,
        "timeout": config.RUN_TIMEOUT_SEC,
    }
    resp = requests.post(
        f"{API}/acts/{actor_path}/runs",
        headers=_headers(), params=params, json=run_input, timeout=60,
    )
    if resp.status_code == 402:
        raise SystemExit("Apify: закончился бесплатный кредит в этом месяце — сбор пропущен.")
    resp.raise_for_status()
    run = resp.json()["data"]
    print(f"[apify] {actor_id}: запуск {run['id']}")

    deadline = time.time() + config.RUN_TIMEOUT_SEC + 120
    status = run["status"]
    while status in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        r = requests.get(f"{API}/actor-runs/{run['id']}", headers=_headers(), timeout=60)
        r.raise_for_status()
        run = r.json()["data"]
        status = run["status"]

    usage = run.get("usageTotalUsd")
    print(f"[apify] статус {status}, стоимость ≈ ${usage if usage is not None else '?'}")
    if status not in ("SUCCEEDED", "TIMED-OUT", "ABORTED"):
        raise RuntimeError(f"Apify run {run['id']} завершился со статусом {status}")

    # Даже при таймауте берём то, что успело собраться
    items = requests.get(
        f"{API}/datasets/{run['defaultDatasetId']}/items",
        headers=_headers(), params={"clean": "true", "format": "json"}, timeout=120,
    )
    items.raise_for_status()
    data = items.json()
    print(f"[apify] получено элементов: {len(data)}")
    return data
