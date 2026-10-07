"""Phone validation and sanitization for public surfaces (TASK-207).

Public pages and APIs must never expose phone values without at least 7 ASCII digits.
Apply sanitization at the data layer (row → card/item), not in each render.
"""

from __future__ import annotations

import re

_SCAN_LIMIT = 256
_MATCH_START_LIMIT = 64
_MAX_PHONE_DIGITS = 15

_ASCII_DIGITS = frozenset("0123456789")
_PHONE_LIKE = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_SEGMENT_SPLIT = re.compile(r"[;,\n]| {2,}")
_CLOCK_COLON = re.compile(r"\d{1,2}:\d{2}")
_DOT_DATE = re.compile(r"\d{4}\.\d{2}\.\d{2}|\d{1,2}\.\d{2}\.\d{4}")
_DOT_TIME = re.compile(r"(?<!\d)\d{1,2}\.\d{2}(?!\.\d)")
_EXT_TAIL = re.compile(r"(?:\s|,)*(?:доб\.?|ext\.?|вн\.?)\s*\d.*$", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ascii_digits(s: str) -> str:
    return "".join(ch for ch in s if ch in _ASCII_DIGITS)


def _should_strip_trailing_paren(inner: str) -> bool:
    if re.search(r"[a-zA-Zа-яА-Я]", inner):
        return True
    if "/" in inner:
        return True
    if _CLOCK_COLON.search(inner):
        return True
    return bool(re.search(r"касса|telegram", inner, re.IGNORECASE))


def _strip_trailing_paren_note(chunk: str) -> str:
    trimmed = chunk.strip()
    while True:
        m = re.search(r"\s*\(([^)]*)\)\s*$", trimmed)
        if not m or not _should_strip_trailing_paren(m.group(1)):
            return trimmed
        trimmed = trimmed[: m.start()].rstrip()


def _trim_incomplete_paren_tail(chunk: str) -> str:
    trimmed = chunk.strip()
    if trimmed.count("(") != trimmed.count(")") and "(" in trimmed:
        trimmed = trimmed[: trimmed.rindex("(")].rstrip()
    return trimmed


def _looks_like_dot_time_range(chunk: str) -> bool:
    stripped = chunk.strip()
    if "+" in stripped or _CLOCK_COLON.search(stripped):
        return False
    dot_parts = _DOT_TIME.findall(stripped)
    if len(dot_parts) < 2:
        return False
    return _ascii_digits(stripped) == _ascii_digits("".join(dot_parts))


def _href_from_phone_like(chunk: str) -> str:
    if _looks_like_dot_time_range(chunk):
        return ""
    trimmed = _trim_incomplete_paren_tail(_EXT_TAIL.sub("", chunk.strip()))
    trimmed = _strip_trailing_paren_note(trimmed)
    if not trimmed or _ISO_DATE.match(trimmed):
        return ""
    plus = trimmed.startswith("+")
    digits = _ascii_digits(trimmed)
    if not 7 <= len(digits) <= _MAX_PHONE_DIGITS:
        return ""
    return f"+{digits}" if plus else digits


def _starts_new_number(token: str) -> bool:
    if token.startswith("+") or token == "8":
        return True
    if _looks_like_dot_time_range(token):
        return True
    compact = len(_ascii_digits(token)) >= 7 and re.search(r"[().\-]", token) is None
    return compact


def _trim_to_first_number(chunk: str) -> str:
    """Keep the first 7..15 digit phone; a later number or a dot-time is a new token."""
    trimmed = _trim_incomplete_paren_tail(_EXT_TAIL.sub("", chunk.strip()))
    trimmed = _strip_trailing_paren_note(trimmed).strip()
    if not trimmed or _ISO_DATE.match(trimmed) or _looks_like_dot_time_range(trimmed):
        return ""
    tokens = list(re.finditer(r"\S+", trimmed))
    digits = 0
    last = 0
    for index, token in enumerate(tokens):
        text = token.group()
        count = len(_ascii_digits(text))
        if digits >= 7 and _starts_new_number(text):
            break
        if digits + count > _MAX_PHONE_DIGITS:
            break
        digits += count
        last = index + 1
    if last == 0 or digits < 7:
        return ""
    return trimmed[: tokens[last - 1].end()]


def _mask_dates_and_clocks(text: str) -> str:
    """Blank dd.mm.yyyy / yyyy.mm.dd and HH:MM in place so indexes stay aligned."""

    def blank(match: re.Match[str]) -> str:
        return " " * len(match.group(0))

    return _CLOCK_COLON.sub(blank, _DOT_DATE.sub(blank, text))


def _segments(masked: str) -> list[tuple[int, str]]:
    pieces: list[tuple[int, str]] = []
    start = 0
    for split in _SEGMENT_SPLIT.finditer(masked):
        pieces.append((start, masked[start : split.start()]))
        start = split.end()
    pieces.append((start, masked[start:]))
    return pieces


def _first_valid_href(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    window = raw[:_SCAN_LIMIT]
    masked = _mask_dates_and_clocks(window)
    clipped = len(raw) > _SCAN_LIMIT
    for offset, segment in _segments(masked):
        if offset >= _MATCH_START_LIMIT:
            break
        for match in _PHONE_LIKE.finditer(segment):
            start = offset + match.start()
            end = offset + match.end()
            if start >= _MATCH_START_LIMIT:
                break
            if clipped and end >= _SCAN_LIMIT:
                continue
            href = _href_from_phone_like(_trim_to_first_number(match.group(0)))
            if href:
                return href
    return ""


def is_valid_public_phone(phone: str | None) -> bool:
    """True when the value contains a dialable phone (≥7 ASCII digits), not only hours."""
    if not phone:
        return False
    return bool(_first_valid_href(phone))


def sanitize_public_phone(phone: str | None) -> str | None:
    """Return phone only if it contains at least 7 ASCII digits, else None."""
    if not phone:
        return None
    raw = str(phone).strip()
    if not raw or not is_valid_public_phone(raw):
        return None
    return raw[:_SCAN_LIMIT]


def tel_href(phone: str) -> str:
    """Digits (and leading +) for tel: URI — first valid phone-like span only."""
    return _first_valid_href(phone)
