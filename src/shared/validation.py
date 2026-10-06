"""
Shared validation helpers for API and bots. Avoid invalid input and overlong text.
"""

import re

# Max lengths for free text stored in DB (Text() columns); avoid huge payloads.
MAX_COMMENT_LEN = 2000
MAX_REVIEW_LEN = 2000


def safe_parse_id(s: str | None) -> int | None:
    """Parse string to non-negative int; None if empty, invalid, or negative."""
    if not s or not s.strip():
        return None
    try:
        n = int(s.strip())
        return n if n >= 0 else None
    except ValueError:
        return None


def truncate_text(s: str | None, max_len: int = 2000) -> str | None:
    """Strip and truncate to max_len; return None if empty after strip."""
    if s is None:
        return None
    t = s.strip()
    return t[:max_len] if t else None


# Угловые скобки и управляющие символы (кроме таба и переводов строк): в названии или адресе
# площадки им места нет, а в публичных страницах и Mini App они — заготовка HTML-инъекции.
# Кавычки, «ёлочки», апостроф и амперсанд — законные («Ледовый дворец "Юность"», «Bowl & Roll»).
_MARKUP_CHARS_RE = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def has_markup_chars(value: str | None) -> bool:
    """True when free text (arena name/address) carries ``<``, ``>`` or control characters."""
    return bool(value) and bool(_MARKUP_CHARS_RE.search(value))
