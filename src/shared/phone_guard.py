"""Phone validation and sanitization for public surfaces (TASK-207).

Public pages and APIs must never expose phone values without at least 7 ASCII digits.
Apply sanitization at the data layer (row → card/item), not in each render.
"""

from __future__ import annotations

import re

_ASCII_DIGITS = frozenset("0123456789")
_MULTI_PHONE_SPLIT = re.compile(r"[;,/]")
_EXT_TAIL = re.compile(r"(?:\s|,)*(?:доб\.?|ext\.?)\s*\d.*$", re.IGNORECASE)
_CLOCK = re.compile(r"\d{1,2}:\d{2}")
_DAY_ABBR = re.compile(r"(?:пн|вт|ср|чт|пт|сб|вс)", re.IGNORECASE)


def _ascii_digits(s: str) -> str:
    return "".join(ch for ch in s if ch in _ASCII_DIGITS)


def _looks_like_business_hours(text: str) -> bool:
    if not _CLOCK.search(text):
        return False
    if _DAY_ABBR.search(text):
        return True
    # e.g. 09:00-18:00 without a country code — not a dialable number.
    if len(_CLOCK.findall(text)) >= 2 and "+" not in text:
        return True
    return False


def _primary_phone_segment(phone: str) -> str:
    raw = str(phone or "").strip()
    if not raw:
        return ""
    parts = _MULTI_PHONE_SPLIT.split(raw, maxsplit=1)
    segment = parts[0].strip()
    segment = _EXT_TAIL.sub("", segment).strip()
    return segment


def is_valid_public_phone(phone: str | None) -> bool:
    """True when the value looks like a dialable phone (≥7 ASCII digits, not opening hours)."""
    if not phone:
        return False
    segment = _primary_phone_segment(phone)
    if not segment or _looks_like_business_hours(segment):
        return False
    return len(_ascii_digits(segment)) >= 7


def sanitize_public_phone(phone: str | None) -> str | None:
    """Return phone only if it contains at least 7 ASCII digits, else None."""
    if not phone:
        return None
    raw = str(phone).strip()
    if not raw or not is_valid_public_phone(raw):
        return None
    return raw


def tel_href(phone: str) -> str:
    """Digits (and leading +) for tel: URI — empty unless is_valid_public_phone()."""
    if not is_valid_public_phone(phone):
        return ""
    segment = _primary_phone_segment(phone)
    return "".join(ch for ch in segment if ch in _ASCII_DIGITS or ch == "+")
