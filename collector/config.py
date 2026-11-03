"""Настройки берутся из переменных окружения (в GitHub Actions — из Secrets и Variables)."""
import os


def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    return int(value) if value else default


def _float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


def _list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, "").strip() or default
    return [x.strip().lstrip("#@") for x in raw.split(",") if x.strip()]


# --- Секреты ---
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

# --- Какие Apify-скраперы использовать ---
# По умолчанию — дешёвые community-скраперы (~$0.30 за 1000 результатов) с тем же
# форматом полей, что у официальных apify/instagram-reel-scraper и apify/instagram-hashtag-scraper.
# Пустая переменная (GitHub подставляет "" для незаданных vars) = значение по умолчанию.
REEL_ACTOR = os.getenv("REEL_ACTOR", "").strip() or "rowfinch/instagram-reel-scraper"
HASHTAG_ACTOR = os.getenv("HASHTAG_ACTOR", "").strip() or "rowfinch/instagram-hashtag-scraper"

# --- Ниша: AI-арт и AI-анимация ---
HASHTAGS = _list(
    "HASHTAGS",
    "aiart,aianimation,aivideo,aiartwork,aicartoon,aishortfilm,aianimated,midjourneyart",
)
HASHTAG_RESULTS = _int("HASHTAG_RESULTS", 40)          # топ-роликов на хэштег при discovery

# --- Отслеживание авторов ---
MAX_CREATORS = _int("MAX_CREATORS", 40)                # сколько авторов держим в работе
REELS_PER_CREATOR = _int("REELS_PER_CREATOR", 5)       # последних роликов за ежедневный прогон
MIN_ENGLISH_SCORE = _float("MIN_ENGLISH_SCORE", 0.6)   # порог «англоязычный автор»

# --- Предохранители бюджета (бесплатно = $5 кредита Apify в месяц) ---
MAX_ITEMS_PER_RUN = _int("MAX_ITEMS_PER_RUN", 100)     # лимит скрапера на бесплатном плане
MAX_CHARGE_PER_RUN_USD = _float("MAX_CHARGE_PER_RUN_USD", 0.25)
RUN_TIMEOUT_SEC = _int("RUN_TIMEOUT_SEC", 900)


def require(*names: str) -> None:
    missing = [n for n in names if not globals().get(n)]
    if missing:
        raise SystemExit(f"Не заданы переменные окружения: {', '.join(missing)}")
