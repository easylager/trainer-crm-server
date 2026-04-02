"""
Trainer profile phone: normalize and validate (API + bot wizard). Belarus E.164 only: +375 + 9 digits.
No imports from api.schemas (avoids cycles).
"""
from __future__ import annotations

import re

# Aligned with DB trainer_profiles.phone String(32)
PHONE_MAX_LEN = 32

# After normalization: +375 + exactly 9 national digits (ITU numbering for Belarus).
_BY_E164 = re.compile(r"^\+375\d{9}$")

_ERR_BY = "Укажите корректный номер телефона."


def normalize_phone_input(value: str | None) -> str:
    """
    Strip and coerce common Belarus inputs to +375XXXXXXXXX when possible:
    - 12 digits starting with 375
    - 11 digits starting with 80 (8 0XX …)
    - 9 digits (national number without country code)
    Otherwise: collapse spaces and common separators (legacy path for error messages).
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    d = "".join(c for c in raw if c.isdigit())
    if not d:
        return raw[:PHONE_MAX_LEN]

    if len(d) == 12 and d.startswith("375"):
        return f"+{d}"
    if len(d) == 11 and d.startswith("80"):
        return "+375" + d[2:]
    if len(d) == 9:
        return "+375" + d

    collapsed = (
        raw.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
    )
    return collapsed[:PHONE_MAX_LEN]


def validate_phone_non_empty(normalized: str) -> tuple[str | None, str | None]:
    """
    Validate non-empty normalized phone. Returns (normalized, None) or (None, Russian error).
    """
    t = normalized
    if not t:
        return None, None
    if len(t) > PHONE_MAX_LEN:
        return None, "Телефон: не длиннее 32 символов."
    if not _BY_E164.match(t):
        return None, _ERR_BY
    return t, None


def coerce_required_belarus_phone(value: object) -> str:
    """
    Required Belarus E.164 for trainer-created client (schedule API).
    Raises ValueError with Russian message (aligned with FastAPI/Pydantic).
    """
    if not isinstance(value, str):
        raise ValueError("Телефон укажите текстом.")
    if not (value or "").strip():
        raise ValueError("Укажите номер телефона.")
    t = normalize_phone_input(value)
    ok, err = validate_phone_non_empty(t)
    if err:
        raise ValueError(err)
    if not ok:
        raise ValueError(_ERR_BY)
    return ok


def coerce_optional_phone_for_profile(value: object) -> str | None:
    """
    API / Pydantic: None or blank -> None; otherwise normalized string or ValueError (Russian message).
    """
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
