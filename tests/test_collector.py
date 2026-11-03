"""Тесты без сети: python -m pytest -q"""
from collector import config, jobs
from collector.normalize import creator_english_score, english_score, normalize_reel

# Формат полей как у apify/instagram-reel-scraper и совместимых скраперов
APIFY_REEL = {
    "id": "4010760174779391973",
    "type": "Video",
    "shortCode": "DepFSEJAl_l",
    "url": "https://www.instagram.com/p/DepFSEJAl_l/",
    "caption": "What if Pixar made this? Tiny robot finds a flower #aiart #AIAnimation",
    "hashtags": ["aiart", "AIAnimation"],
    "ownerUsername": "Pixel.Dreamer",
    "videoPlayCount": 152340,
    "videoViewCount": 99000,
    "likesCount": 8100,
    "commentsCount": 120,
    "videoDuration": 14.6,
    "timestamp": "2026-10-30T18:22:05.000Z",
    "displayUrl": "https://scontent.cdninstagram.com/x.jpg",
}


def test_normalize_reel_fields():
    r = normalize_reel(APIFY_REEL, "track")
    assert r["short_code"] == "DepFSEJAl_l"
    assert r["username"] == "pixel.dreamer"
    assert r["views"] == 152340                      # play count важнее view count
    assert r["likes"] == 8100 and r["comments"] == 120
    assert r["hashtags"] == ["aianimation", "aiart"]
    assert r["posted_at"].startswith("2026-10-30T18:22:05")
    assert r["duration_sec"] == 14.6


def test_normalize_alt_fields_and_hidden_likes():
    item = {"url": "https://www.instagram.com/reel/ABC123/", "owner": {"username": "x"},
            "playCount": 10, "likesCount": -1, "takenAt": 1761848525, "caption": "hi #Cozy"}
    r = normalize_reel(item, "hashtag")
    assert r["short_code"] == "ABC123" and r["username"] == "x"
    assert r["likes"] is None                        # скрытые лайки
    assert r["hashtags"] == ["cozy"]
    assert r["posted_at"].startswith("2025-10-30")


def test_normalize_skips_photos_and_errors():
    assert normalize_reel({"shortCode": "p", "ownerUsername": "x", "likesCount": 5}, "track") is None
    assert normalize_reel({"error": "not_found", "url": "x"}, "track") is None


def test_english_score():
    assert english_score("This took 6 hours and 400 generations, what do you think?") > 0.8
    assert english_score("Это заняло шесть часов и много генераций") < 0.3
    assert english_score("Esto me tomó seis horas, ¿qué opinan?") < english_score("This took me six hours, what do you think?")
    assert english_score("#aiart #aivideo #midjourney") is None   # одни хэштеги — язык неизвестен
    assert creator_english_score(["", "#aiart", "Made with love for you all"]) > 0.6


class FakeDB:
    def __init__(self, creators):
        self.creators = {c["username"]: dict(c) for c in creators}
        self.saved = []

    def select(self, table, params):
        rows = list(self.creators.values())
        if "status" in params:
            rows = [r for r in rows if r.get("status") == params["status"].split(".", 1)[1]]
        if "english_score" in params:
            th = float(params["english_score"].split(".", 1)[1])
            rows = [r for r in rows if (r.get("english_score") or 0) >= th]
        if params.get("order", "").startswith("best_views"):
            rows.sort(key=lambda r: -(r.get("best_views") or 0))
        return rows[: params.get("limit", len(rows))]

    def update(self, table, match, values):
        names = match["username"]
        targets = ([names[3:]] if names.startswith("eq.")
                   else [n.strip('"') for n in names[4:-1].split(",")])
        for n in targets:
            row = self.creators.get(n)
            if row and not (match.get("status") == "neq.blocked" and row["status"] == "blocked"):
                row.update(values)

    def upsert(self, table, rows, on_conflict, ignore_duplicates=False):
        for r in rows:
            if r["username"] in self.creators:
                if not ignore_duplicates:
                    self.creators[r["username"]].update(r)
            else:
                self.creators[r["username"]] = {"status": "candidate", **r}

    def save_reels(self, reels):
        self.saved.extend(reels)

    @staticmethod
    def now_iso():
        return "2026-11-03T00:00:00+00:00"


def _patch(monkeypatch, fake, items):
    calls = []
    monkeypatch.setattr(config, "APIFY_TOKEN", "t")
    monkeypatch.setattr(config, "SUPABASE_URL", "u")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "k")
    monkeypatch.setattr(jobs, "_load_seeds", lambda: [])
    for name in ("select", "update", "upsert", "save_reels", "now_iso"):
        monkeypatch.setattr(jobs.db, name, getattr(fake, name))
    monkeypatch.setattr(jobs.apify, "run_actor",
                        lambda actor, inp, max_items: calls.append((actor, inp, max_items)) or items)
    return calls


def _reel(code, user, views, caption):
    return {"shortCode": code, "ownerUsername": user, "videoPlayCount": views,
            "caption": caption, "timestamp": "2026-11-01T00:00:00Z"}


def test_discover_promotes_english_candidates(monkeypatch):
    fake = FakeDB([{"username": "keep", "status": "tracked"}, {"username": "ban", "status": "blocked"}])
    items = [
        _reel("1", "en_big", 900000, "This is what happens when you animate a dream #aiart"),
        _reel("2", "en_small", 20000, "Made this for you, what do you think?"),
        _reel("3", "ru_big", 990000, "Это моя новая анимация, как вам?"),
        _reel("4", "ban", 5000000, "This is the best one you will see today"),
    ]
    monkeypatch.setattr(config, "MAX_CREATORS", 2)
    monkeypatch.setattr(config, "HASHTAGS", ["aiart", "aivideo"])  # одна пачка
    calls = _patch(monkeypatch, fake, items)
    jobs.discover()
    assert calls[0][1]["resultsType"] == "reels"
    assert len(fake.saved) == 4
    assert fake.creators["en_big"]["status"] == "tracked"       # заняла единственное свободное место
    assert fake.creators["en_small"]["status"] == "candidate"   # мест больше нет
    assert fake.creators["ru_big"]["status"] == "candidate"     # не англоязычный
    assert fake.creators["ban"]["status"] == "blocked"          # блок не снимается


def test_track_updates_and_demotes(monkeypatch):
    fake = FakeDB([
        {"username": "a", "status": "tracked", "source": None},
        {"username": "b", "status": "tracked", "source": "seed"},
        {"username": "c", "status": "tracked", "source": None},
    ])
    ru = "Новая анимация, как вам такое?"
    items = [_reel("1", "a", 100, "This is so cool, made with love for you")] + \
            [_reel(f"c{i}", "c", 100, ru) for i in range(3)] + \
            [_reel(f"b{i}", "b", 100, ru) for i in range(3)]
    calls = _patch(monkeypatch, fake, items)
    jobs.track()
    assert calls[0][1]["username"] == ["a", "b", "c"]
    assert fake.creators["a"]["last_tracked_at"]
    assert fake.creators["c"]["status"] == "candidate"   # неанглоязычный — исключён
    assert fake.creators["b"]["status"] == "tracked"     # добавлен вручную — остаётся


def test_empty_env_vars_fall_back_to_defaults(monkeypatch):
    import importlib
    for name in ("REEL_ACTOR", "HASHTAG_ACTOR", "HASHTAGS", "MAX_CREATORS", "MIN_ENGLISH_SCORE"):
        monkeypatch.setenv(name, "")
    cfg = importlib.reload(config)
    try:
        assert cfg.REEL_ACTOR == "rowfinch/instagram-reel-scraper"
        assert cfg.HASHTAG_ACTOR == "rowfinch/instagram-hashtag-scraper"
        assert "aiart" in cfg.HASHTAGS and cfg.MAX_CREATORS == 40 and cfg.MIN_ENGLISH_SCORE == 0.6
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_runs_are_split_into_batches(monkeypatch):
    fake = FakeDB([{"username": f"u{i}", "status": "tracked", "source": None} for i in range(25)])
    calls = _patch(monkeypatch, fake, [])
    monkeypatch.setattr(config, "MAX_ITEMS_PER_RUN", 100)
    monkeypatch.setattr(config, "REELS_PER_CREATOR", 10)
    jobs.track()
    assert [len(c[1]["username"]) for c in calls] == [10, 10, 5]
    assert all(c[2] <= 100 and c[1]["resultsLimit"] == 10 for c in calls)
