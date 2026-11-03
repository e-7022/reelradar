"""Приведение ответов разных Apify-скраперов к одному формату + эвристика англоязычности."""
import re
from datetime import datetime, timezone

SHORTCODE_RE = re.compile(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)")
HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)
MENTION_RE = re.compile(r"[@#]\w+", re.UNICODE)
URL_RE = re.compile(r"https?://\S+")
WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʻ][^\W\d_]+)*", re.UNICODE)

# Служебные слова английского — признак англоязычной подписи.
EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "this",
    "that", "is", "are", "was", "were", "it", "its", "my", "your", "you", "i", "me", "we",
    "our", "us", "what", "when", "how", "why", "if", "so", "just", "be", "been", "do", "did",
    "not", "all", "by", "from", "at", "as", "can", "will", "would", "who", "they", "their",
    "he", "she", "his", "her", "him", "them", "there", "here", "have", "has", "had", "about",
    "into", "out", "up", "one", "every", "never", "only", "than", "then", "too", "very",
    "made", "make", "new", "like", "follow", "comment", "share", "watch", "get", "got",
}

# Служебные слова языков, которые в нише AI-видео часто пишут латиницей.
# Слова, совпадающие с английскими (me, son, men, ham, hi…), сюда не включены.
FOREIGN_STOPWORDS = {
    # хинди / урду латиницей (хинглиш)
    "hai", "hain", "ka", "ki", "ke", "ko", "ne", "se", "kya", "aur", "mein", "mai", "nahi",
    "nhi", "bhi", "kar", "kr", "ye", "yeh", "woh", "wo", "ek", "tha", "thi", "liye", "jo",
    "kis", "koi", "sab", "apne", "apna", "diya", "gaya", "gayi", "raha", "rahi", "bhai", "wala",
    "wali", "toh", "pe", "par", "ab", "esa", "aisa", "kaise", "kyun", "sath", "saath", "bahut",
    "hum", "tum", "aap", "mera", "meri", "tera", "teri", "kuch", "abhi", "chahiye", "lekin",
    # узбекский
    "va", "bilan", "uchun", "emas", "bu", "siz", "biz", "edi", "qilib", "kerak", "yoki",
    "qoʻyamiz", "qo'yamiz", "boʻling", "bo'ling", "obuna", "narxi", "hammamizning",
    # индонезийский / малайский
    "dan", "yang", "di", "ini", "itu", "aku", "saat", "sedang", "dengan", "untuk", "tidak",
    "ada", "kamu", "juga", "sendiri", "jika", "akan", "dari", "sudah", "lagi", "kita", "nya",
    # португальский / испанский / итальянский
    "que", "não", "nao", "com", "isso", "já", "uma", "para", "você", "voce", "tão", "mais",
    "muito", "el", "la", "los", "las", "es", "por", "con", "del", "esta", "esto", "pero",
    "muy", "y", "hago", "verdad", "lo", "su", "como", "cuando", "nos", "il", "di", "che",
    "feito", "eita", "aqui", "você",
    # французский
    "le", "les", "des", "et", "est", "une", "avec", "dans", "pas", "qui", "du",
    "au", "sur", "nouvel", "épisode", "partie", "sous", "ce", "cette", "mon", "ma", "je",
    # турецкий
    "ve", "bir", "ile", "için", "bu", "kere", "oldu", "böyle", "çok", "daha", "gibi", "ama",
    "değil", "şimdi", "şansını",
    # немецкий
    "und", "der", "das", "ist", "nicht", "ich", "mit", "auf", "ein", "eine",
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
    """0..1 — насколько подпись похожа на английский текст. None, если судить не по чему.

    Хэштеги, упоминания и ссылки убираются: в нише AI-видео они почти всегда английские
    и ничего не говорят о языке автора. Дальше сравниваются служебные слова английского
    и других языков, которые часто пишут латиницей (хинглиш, узбекский, индонезийский…).
    """
    if not text:
        return None
    clean = URL_RE.sub(" ", MENTION_RE.sub(" ", text))
    letters = [c for c in clean if c.isalpha()]
    if len(letters) < 8:
        return None
    latin_ratio = sum("a" <= c.lower() <= "z" for c in letters) / len(letters)
    if latin_ratio < 0.5:
        return round(latin_ratio * 0.3, 3)          # деванагари, кириллица, CJK…
    words = WORD_RE.findall(clean.lower())
    en = sum(w in EN_STOPWORDS for w in words)
    foreign = sum(w in FOREIGN_STOPWORDS for w in words)
    if "ʻ" in clean:                                  # узбекская «оʻ»
        foreign += 2
    if en + foreign == 0:
        return None                                   # «Sunday Service», «Mr Chow» — неясно
    return round(latin_ratio * en / (en + foreign), 3)


def creator_language(captions: list[str]):
    """(средний english_score, сколько подписей удалось оценить)."""
    scores = [s for s in (english_score(c) for c in captions) if s is not None]
    if not scores:
        return None, 0
    return round(sum(scores) / len(scores), 3), len(scores)


def creator_english_score(captions: list[str]):
    """Средний english_score по подписям автора (без неоценённых)."""
    return creator_language(captions)[0]
