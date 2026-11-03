"""Две задачи:
  discover — раз в неделю ищет топ-Reels по хэштегам ниши и находит новых авторов;
  track    — раз в день обновляет последние ролики отслеживаемых авторов.
"""
from collections import defaultdict
from pathlib import Path

from . import apify, config, db
from .normalize import creator_english_score, normalize_reel

SEEDS_FILE = Path(__file__).resolve().parent.parent / "seeds.txt"


def _in(values) -> str:
    quoted = ",".join('"' + v.replace('"', "") + '"' for v in values)
    return f"in.({quoted})"


def _load_seeds() -> list[str]:
    if not SEEDS_FILE.exists():
        return []
    seeds = []
    for line in SEEDS_FILE.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip().lstrip("@").lower()
        if name:
            seeds.append(name)
    return seeds


def _apply_seeds() -> None:
    seeds = _load_seeds()
    if not seeds:
        return
    db.upsert("creators", [{"username": s, "status": "tracked", "source": "seed"} for s in seeds],
              on_conflict="username", ignore_duplicates=True)
    # уже существующих (кроме заблокированных) тоже переводим в отслеживаемые
    db.update("creators", {"username": _in(seeds), "status": "neq.blocked"},
              {"status": "tracked", "source": "seed"})
    print(f"[seeds] авторов из seeds.txt: {len(seeds)}")


def _run_batched(actor: str, key: str, values: list[str], per_value: int, extra: dict) -> list[dict]:
    """Запускает Actor пачками, чтобы каждый запуск укладывался в MAX_ITEMS_PER_RUN.

    На бесплатном плане Apify многие скраперы отдают не больше 100 результатов за запуск.
    """
    per_value = max(1, min(per_value, config.MAX_ITEMS_PER_RUN))
    size = max(1, config.MAX_ITEMS_PER_RUN // per_value)
    items, failed = [], 0
    batches = [values[i:i + size] for i in range(0, len(values), size)]
    for n, batch in enumerate(batches, 1):
        print(f"[batch {n}/{len(batches)}] {key}: {len(batch)}")
        try:
            items += apify.run_actor(actor, {key: batch, "resultsLimit": per_value, **extra},
                                     max_items=len(batch) * per_value)
        except SystemExit:
            raise                      # кончился кредит — дальше нет смысла
        except Exception as exc:       # одна сломанная пачка не должна валить остальные
            failed += 1
            print(f"[batch {n}] ошибка: {exc}")
    if batches and failed == len(batches):
        raise RuntimeError("все запуски Apify завершились ошибкой")
    return items


def discover() -> None:
    config.require("APIFY_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY")
    _apply_seeds()

    items = _run_batched(config.HASHTAG_ACTOR, "hashtags", config.HASHTAGS,
                         config.HASHTAG_RESULTS, {"resultsType": "reels", "order": "top"})
    reels = [r for r in (normalize_reel(i, "hashtag") for i in items) if r]
    db.save_reels(reels)
    print(f"[discover] сохранено роликов: {len(reels)}")

    # Кандидаты в авторы. status в payload нет → у существующих авторов он не меняется.
    captions, best = defaultdict(list), defaultdict(int)
    for r in reels:
        captions[r["username"]].append(r["caption"])
        best[r["username"]] = max(best[r["username"]], r["views"])
    db.upsert("creators", [
        {"username": u, "english_score": creator_english_score(captions[u]), "best_views": best[u]}
        for u in captions
    ], on_conflict="username")

    # Повышаем лучших англоязычных кандидатов до отслеживаемых, пока есть места
    tracked = db.select("creators", {"select": "username", "status": "eq.tracked"})
    slots = config.MAX_CREATORS - len(tracked)
    if slots <= 0:
        print(f"[discover] свободных мест нет ({len(tracked)}/{config.MAX_CREATORS})")
        return
    promote = db.select("creators", {
        "select": "username,english_score,best_views",
        "status": "eq.candidate",
        "english_score": f"gte.{config.MIN_ENGLISH_SCORE}",
        "order": "best_views.desc.nullslast",
        "limit": slots,
    })
    if promote:
        db.update("creators", {"username": _in([p["username"] for p in promote])},
                  {"status": "tracked"})
    print(f"[discover] новых отслеживаемых авторов: {len(promote)} "
          f"(всего {len(tracked) + len(promote)}/{config.MAX_CREATORS})")


def track() -> None:
    config.require("APIFY_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_KEY")
    _apply_seeds()

    creators = db.select("creators", {
        "select": "username,source",
        "status": "eq.tracked",
        "order": "last_tracked_at.asc.nullsfirst",
        "limit": config.MAX_CREATORS,
    })
    if not creators:
        print("[track] нет отслеживаемых авторов. Запустите discover или заполните seeds.txt.")
        return
    usernames = [c["username"] for c in creators]

    items = _run_batched(config.REEL_ACTOR, "username", usernames,
                         config.REELS_PER_CREATOR, {"skipPinnedPosts": True})
    reels = [r for r in (normalize_reel(i, "track") for i in items) if r]
    db.save_reels(reels)
    db.update("creators", {"username": _in(usernames)}, {"last_tracked_at": db.now_iso()})

    # Уточняем англоязычность по свежим подписям; явно неанглоязычных
    # (кроме добавленных вручную) возвращаем в кандидаты — освобождаем место.
    captions = defaultdict(list)
    for r in reels:
        captions[r["username"]].append(r["caption"])
    demoted = 0
    seeds = {c["username"] for c in creators if c.get("source") == "seed"}
    for username, caps in captions.items():
        score = creator_english_score(caps)
        if score is None:
            continue
        values = {"english_score": score}
        if score < config.MIN_ENGLISH_SCORE - 0.2 and len(caps) >= 3 and username not in seeds:
            values["status"] = "candidate"
            demoted += 1
        db.update("creators", {"username": f"eq.{username}"}, values)

    print(f"[track] авторов: {len(usernames)}, роликов: {len(reels)}, "
          f"исключено как неанглоязычные: {demoted}")
