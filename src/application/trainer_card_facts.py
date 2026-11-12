"""Плашка фактов карточки тренера (SPEC §4). Та же таблица кейсов, что у Mini App.

Порядок: опыт → кого учит → каток, если публичное название ≤ 10 знаков, иначе цена.
Меньше двух фактов — пустой список. Счётчик занятий и рейтинг сюда не входят.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.application.ice_city_day import format_price_minor
from src.shared.ru_text import count_ru

# «Взрослый + ребёнок» — не «только дети»: в тарифе есть взрослый.
_KID_ONLY = frozenset({"child", "two_children"})

_EXPERIENCE = "тренерского опыта"
_STUDENTS = "учеников"
_RINK = "основной каток"
_PRICE = "за занятие"


def audience_label(tier_kinds: Sequence[str] | None) -> str:
    """«Дети» только если каждый тариф детский. Иначе «Любой возраст», в том числе при пустом списке."""
    kinds = [str(k) for k in (tier_kinds or []) if k]
    if kinds and all(k in _KID_ONLY for k in kinds):
        return "Дети"
    return "Любой возраст"


def _years(value: Any) -> int | None:
    """Только целое число. Строка, дробь и bool опыта не дают."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 1 else None


def _price_cents(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    cents = int(value)
    return cents if cents > 0 else None


def _rink_value(name: Any) -> str | None:
    text = str(name or "").strip()
    if not text or len(text) > 10:
        return None
    if text.startswith("«") and text.endswith("»"):
        return text
    return f"«{text}»"


def fact_strip(case: Mapping[str, Any]) -> list[dict[str, str]]:
    """До трёх фактов ``{value, label}``. 0 или 1 кандидат — ``[]``."""
    facts: list[dict[str, str]] = []
    years = _years(case.get("experience_years"))
    if years is not None:
        facts.append({"value": count_ru(years, "год", "года", "лет"), "label": _EXPERIENCE})
    facts.append({"value": audience_label(case.get("tier_kinds")), "label": _STUDENTS})
    rink = _rink_value(case.get("rink_name"))
    if rink:
        facts.append({"value": rink, "label": _RINK})
    cents = _price_cents(case.get("price_cents"))
    if cents is not None:
        facts.append(
            {
                "value": "от " + format_price_minor(cents, str(case.get("currency") or "BYN")),
                "label": _PRICE,
            }
        )
    if len(facts) < 2:
        return []
    return facts[:3]
