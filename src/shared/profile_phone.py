"""
Phone normalize and validate (API + bot + Mini App). Supported: Belarus (+375) and Russia (+7).
No imports from api.schemas (avoids cycles).
"""
from __future__ import annotations

import re

PHONE_MAX_LEN = 32

_BY_E164 = re.compile(r"^\+375\d{9}$")
_RU_E164 = re.compile(r"^\+7\d{10}$")
_SUPPORTED_COUNTRIES = frozenset({"BY", "RU"})

_ERR = "Укажите корректный номер телефона."


def strip_phone_digits(value: str | None) -> str:
    if not value:
        return ""
    return "".join(c for c in value.strip() if c.isdigit())


def detect_country_from_digits(digits: str) -> str | None:
    """Best-effort ISO-ish country code from digit string (no +)."""
    d = digits or ""
    while len(d) >= 2 and d.startswith("00"):
        d = d[2:]
    if len(d) >= 12 and d.startswith("375"):
        return "BY"
    if len(d) == 11 and d.startswith("80"):
        return "BY"
    if len(d) == 11 and d.startswith("8"):
        return "RU"
    if len(d) >= 11 and d.startswith("7"):
        return "RU"
    if len(d) == 10 and d and d[0] == "9":
        return "RU"
    if len(d) == 9:
        return "BY"
    return None


def _collapse_separators(raw: str) -> str:
    return (
        raw.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
    )[:PHONE_MAX_LEN]


def _normalize_by_digits(d: str) -> str | None:
    while len(d) >= 2 and d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("80"):
        d = "375" + d[2:]
    elif len(d) == 9:
        d = "375" + d
    elif len(d) > 12 and d.startswith("375"):
        d = d[:12]
    if len(d) == 12 and d.startswith("375"):
        return d
    return None


def _normalize_ru_digits(d: str) -> str | None:
    while len(d) >= 2 and d.startswith("00"):
        d = d[2:]
    if len(d) == 11 and d.startswith("8"):
        d = "7" + d[1:]
    elif len(d) == 10 and d and d[0] == "9":
        d = "7" + d
    elif len(d) > 11 and d.startswith("7"):
        d = d[:11]
    if len(d) == 11 and d.startswith("7"):
        return d
    return None


def normalize_phone_input(value: str | None, country: str | None = None) -> str:
    """
    Coerce common BY/RU inputs to E.164 when possible.
    ``country``: ``BY`` | ``RU`` — when UI already picked country; else auto-detect (default BY).
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    d = strip_phone_digits(raw)
    if not d:
        return _collapse_separators(raw)

    cc = (country or "").upper()
    if cc not in _SUPPORTED_COUNTRIES:
        cc = detect_country_from_digits(d) or "BY"

    if cc == "RU":
        nd = _normalize_ru_digits(d)
        return f"+{nd}" if nd else _collapse_separators(raw)

    nd = _normalize_by_digits(d)
    return f"+{nd}" if nd else _collapse_separators(raw)


def is_valid_e164_phone(normalized: str) -> bool:
    return bool(_BY_E164.match(normalized) or _RU_E164.match(normalized))


def validate_phone_non_empty(normalized: str) -> tuple[str | None, str | None]:
    """Validate non-empty normalized phone. Returns (E.164, None) or (None, Russian error)."""
    t = normalized
    if not t:
        return None, None
    if len(t) > PHONE_MAX_LEN:
        return None, "Телефон: не длиннее 32 символов."
    if is_valid_e164_phone(t):
        return t, None
    return None, _ERR


def e164_to_lookup_digits(e164: str) -> str:
    """Digits-only for ``phone_normalized`` column (375… or 7…)."""
    return strip_phone_digits(e164)


def coerce_required_phone(value: object, country: str | None = None) -> str:
    """Required BY/RU E.164 for trainer-created client and similar APIs."""
    if not isinstance(value, str):
        raise ValueError("Телефон укажите текстом.")
    if not (value or "").strip():
        raise ValueError("Укажите номер телефона.")
    t = normalize_phone_input(value, country=country)
    ok, err = validate_phone_non_empty(t)
    if err:
        raise ValueError(err)
    if not ok:
        raise ValueError(_ERR)
    return ok


def coerce_required_belarus_phone(value: object) -> str:
    """Backward-compatible alias — accepts RU numbers too."""
    return coerce_required_phone(value)


def coerce_optional_phone_for_profile(value: object) -> str | None:
    """API / Pydantic: None or blank -> None; otherwise normalized E.164 or ValueError."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if not isinstance(value, str):
        raise ValueError("Телефон укажите текстом.")
    t = normalize_phone_input(value)
    if not t:
        return None
    ok, err = validate_phone_non_empty(t)
    if err:
        raise ValueError(err)
    return ok
