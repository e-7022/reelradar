"""Приведение ответов разных Apify-скраперов к одному формату + эвристика англоязычности."""
import re
from datetime import datetime, timezone

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"[@#]\w+", re.UNICODE)
URL_RE = re.compile(r"https?://\S+")
WORD_RE = re.compile(r"[a-z']+")

EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "this",
    "that", "is", "are", "was", "it", "my", "your", "you", "i", "me", "we", "our", "what",
    "when", "how", "if", "so", "just", "be", "do", "not", "all", "by", "from", "at", "as",
    "can", "will", "made", "make", "who", "new", "like", "follow", "comment", "share", "would",
}


def _first_int(item: dict, *keys: str):
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _parse_time(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 1e12 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _shortcode(item: dict):
    code = item.get("shortCode") or item.get("shortcode") or item.get("code")
    if code:
        return str(code)
    for key in ("url", "inputUrl"):
        match = SHORTCODE_RE.search(str(item.get(key) or ""))
        if match:
            return match.group(1)
    return None


def normalize_reel(item: dict, source: str):
    """Один элемент Apify → строка таблицы reels. None, если это не видео/нет данных."""
    if item.get("error") or item.get("errorDescription"):
        return None
    code = _shortcode(item)
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    username = item.get("ownerUsername") or owner.get("username")
    views = _first_int(item, "videoPlayCount", "playCount", "videoViewCount", "viewCount", "plays")
    if not code or not username or views is None:
        return None  # фото, карусели и пустые строки пропускаем

    caption = item.get("caption") or ""
    tags = item.get("hashtags")
    if not isinstance(tags, list) or not tags:
        tags = HASHTAG_RE.findall(caption)
    tags = sorted({str(t).lstrip("#").lower() for t in tags if t})

    duration = item.get("videoDuration") or item.get("duration")
    return {
        "short_code": code,
        "username": str(username).lower(),
        "url": item.get("url") or f"https://www.instagram.com/reel/{code}/",
        "caption": caption[:2000],
        "thumbnail_url": item.get("displayUrl") or item.get("thumbnailUrl"),
        "hashtags": tags,
        "duration_sec": float(duration) if isinstance(duration, (int, float)) else None,
        "posted_at": _parse_time(item.get("timestamp") or item.get("takenAt") or item.get("taken_at")),
        "source": source,
        "views": views,
        "likes": _first_int(item, "likesCount", "likeCount"),
        "comments": _first_int(item, "commentsCount", "commentCount"),
    }


def english_score(text: str):
    """0..1 — насколько подпись похожа на английский текст. None, если слов нет.

    Хэштеги, упоминания и ссылки убираются: в нише AI-арта они почти всегда латиницей
    и ничего не говорят о языке автора.
    """
    if not text:
        return None
    clean = URL_RE.sub(" ", MENTION_RE.sub(" ", text))
    letters = [c for c in clean if c.isalpha()]
    if len(letters) < 8:
        return None
    latin_ratio = sum("a" <= c.lower() <= "z" for c in letters) / len(letters)
    words = WORD_RE.findall(clean.lower())
    if not words:
        return round(latin_ratio * 0.5, 3)
    stop_ratio = sum(w in EN_STOPWORDS for w in words) / len(words)
    return round(0.6 * latin_ratio + 0.4 * min(stop_ratio * 4, 1.0), 3)


def creator_english_score(captions: list[str]):
    """Средний english_score по подписям автора (без пустых)."""
    scores = [s for s in (english_score(c) for c in captions) if s is not None]
    return round(sum(scores) / len(scores), 3) if scores else None
