"""Phone validation and sanitization for public surfaces (TASK-207).

Public pages and APIs must never expose phone values without at least 7 ASCII digits.
Apply sanitization at the data layer (row → card/item), not in each render.
"""

from __future__ import annotations

import re

_MAX_PHONE_INPUT_LEN = 64

_ASCII_DIGITS = frozenset("0123456789")
_PHONE_LIKE = re.compile(r"\+?\d[\d\s().-]{5,}\d")
_CLOCK_COLON = re.compile(r"\d{1,2}:\d{2}")
_DOT_TIME = re.compile(r"(?<!\d)\d{1,2}\.\d{2}(?!\.\d)")
_DAY_WORD = re.compile(r"\b(пн|вт|ср|чт|пт|сб|вс)\b", re.IGNORECASE)
_EXT_TAIL = re.compile(r"(?:\s|,)*(?:доб\.?|ext\.?|вн\.?)\s*\d.*$", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEGMENT_SPLIT = re.compile(r"[;,\n]|(?<!\d)/(?=\+?\d)")


def _clip_phone_input(phone: str | None) -> str:
    return str(phone or "").strip()[:_MAX_PHONE_INPUT_LEN]


def _strip_colon_times(text: str) -> str:
    return _CLOCK_COLON.sub(" ", text)


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
    if len(digits) < 7:
        return ""
    return f"+{digits}" if plus else digits


def _any_phone_href_in(text: str) -> bool:
    for chunk in _iter_phone_like_chunks(text):
        for m in _PHONE_LIKE.finditer(_strip_colon_times(chunk)):
            if _href_from_phone_like(m.group(0)):
                return True
    return False


def _is_hours_only_string(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if _ISO_DATE.match(raw):
        return True
    colon_clocks = _CLOCK_COLON.findall(raw)
    dot_clocks = _DOT_TIME.findall(raw)
    if not colon_clocks and not dot_clocks:
        return False
    if _DAY_WORD.search(raw) and not _any_phone_href_in(raw):
        return True
    if re.search(r"ежедневно", raw, re.IGNORECASE) and _CLOCK_COLON.search(raw) and not _any_phone_href_in(raw):
        return True
    if len(dot_clocks) >= 2 and "+" not in raw and not _any_phone_href_in(raw):
        return True
    if len(colon_clocks) >= 2 and "+" not in raw and not _any_phone_href_in(raw):
        return True
    return False


def _iter_phone_like_chunks(text: str) -> list[str]:
    """Left-to-right chunks: explicit segments, then embedded phone-like spans."""
    raw = str(text or "").strip()
    if not raw:
        return []
    seen: set[str] = set()
    ordered: list[str] = []

    def add(chunk: str) -> None:
        c = chunk.strip()
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)

    for seg in _SEGMENT_SPLIT.split(raw):
        add(seg)
    prepared = _strip_colon_times(raw)
    for m in _PHONE_LIKE.finditer(prepared):
        add(m.group(0))
    return ordered


def _first_valid_href(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    if _is_hours_only_string(raw):
        return ""
    for chunk in _iter_phone_like_chunks(raw):
        if _is_hours_only_string(chunk):
            continue
        for m in _PHONE_LIKE.finditer(_strip_colon_times(chunk)):
            href = _href_from_phone_like(m.group(0))
            if href:
                return href
    return ""


def is_valid_public_phone(phone: str | None) -> bool:
    """True when the value contains a dialable phone (≥7 ASCII digits), not only hours."""
    if not phone:
        return False
    return bool(_first_valid_href(_clip_phone_input(phone)))


def sanitize_public_phone(phone: str | None) -> str | None:
    """Return phone only if it contains at least 7 ASCII digits, else None."""
    if not phone:
        return None
    raw = _clip_phone_input(phone)
    if not raw or not is_valid_public_phone(raw):
        return None
    return raw


def tel_href(phone: str) -> str:
    """Digits (and leading +) for tel: URI — first valid phone-like span only."""
    return _first_valid_href(_clip_phone_input(phone))
