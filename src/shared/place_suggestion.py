"""Validation and normalization of a user-submitted place (PDEC-028). Pure, no I/O."""
from __future__ import annotations

import re
from typing import Any

KINDS = ("ice", "outdoor", "shop", "school", "other")
RINK_KINDS = frozenset({"ice", "outdoor"})
#: «Магазин, мастерская»: мастерская — это услуга «repair», а не отдельный тип места.
SHOP_SERVICES = ("sharpening", "repair", "rental", "sale")
#: Для чего магазин — та же специализация, что показывает карточка (discipline_*).
SHOP_DISCIPLINES = ("hockey", "figure", "roller")
SCHOOL_DISCIPLINES = ("figure", "hockey")

#: callback_data кнопки «Одобрить как есть» в уведомлении админу: ``psa:<id>``.
PLACE_SUGGEST_APPROVE_PREFIX = "psa:"

_COMMON_TEXT = {"hours": 300, "link": 300, "more": 1000}
_KIND_TEXT = {
    "ice": {"price_adult": 20, "price_child": 20, "price_rental": 20},
    "outdoor": {"price_adult": 20, "price_child": 20, "price_rental": 20},
    "shop": {},
    "school": {"age": 100},
    "other": {},
}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TG_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")


class PlaceSuggestionError(ValueError):
    """User-facing validation error; message is Russian and safe to show."""


def _clean(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def classify_contact(raw: str | None) -> tuple[str | None, str | None]:
    s = _clean(raw, 120)
    if not s:
        return None, None
    if _EMAIL_RE.match(s):
        return s, "email"
    m = _TG_RE.match(s)
    if m:
        return f"@{m.group(1)}", "telegram"
    return s, "other"


def _as_list(value: Any) -> list[Any]:
    """Только настоящий список: строка «sharpening,sale» или число — это «ничего не выбрано»."""
    return value if isinstance(value, list) else []


def normalize_details(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    out: dict[str, Any] = {}
    for key, limit in {**_KIND_TEXT.get(kind, {}), **_COMMON_TEXT}.items():
        v = _clean(raw.get(key), limit)
        if v:
            out[key] = v
    if kind == "shop":
        picked = [s for s in SHOP_SERVICES if s in _as_list(raw.get("services"))]
        if picked:
            out["services"] = picked
        picked = [s for s in SHOP_DISCIPLINES if s in _as_list(raw.get("disciplines"))]
        if picked:
            out["disciplines"] = picked
    if kind == "school":
        picked = [s for s in SCHOOL_DISCIPLINES if s in _as_list(raw.get("disciplines"))]
        if picked:
            out["disciplines"] = picked
    return out


def validate_core(*, kind: str, city_id: int | None, new_city_name: str | None, name: str) -> tuple[str | None, str]:
    if kind not in KINDS:
        raise PlaceSuggestionError("Выберите, что это за место.")
    city = _clean(new_city_name, 120) or None
    if city_id is None and not city:
        raise PlaceSuggestionError("Укажите город.")
    nm = _clean(name, 200)
    if not nm:
        raise PlaceSuggestionError("Напишите название или пару слов о месте.")
    return city, nm
