"""
Тип площадки: арена — частный случай, а не синоним.

До этого модуля сущность ``arenas`` молча означала «каток», и допущение было
зашито в UI (снежинка в табе, «карточка катка», «Сайт катка»). Первый же тренер
не со льда — зал на Машерова, арена #201 — сломал его во всех местах разом.

Набор типов определяется тем, что реально создают тренеры: арена (лёд),
спортзал, роллердром, уличная площадка, другое. Хореография и бассейн —
не самостоятельные площадки, а зоны внутри арены или зала, поэтому
отдельными типами не выделены.

Падежи держим здесь, а не в шаблонах: «карточка арены» → «карточка зала»
подставляется в одну строку копирайта, и склонять её в трёх местах руками —
верный способ получить «карточка зал».

Клиентский двойник: ``static/webapp/venue-types.js`` (те же ключи и подписи).
"""
from __future__ import annotations

from typing import Any, Mapping

VENUE_TYPE_ARENA = "arena"
VENUE_TYPE_GYM = "gym"
VENUE_TYPE_ROLLER = "roller"
VENUE_TYPE_OUTDOOR = "outdoor"
VENUE_TYPE_OTHER = "other"

DEFAULT_VENUE_TYPE = VENUE_TYPE_ARENA

#: ``chip`` — фильтр в каталоге, ``noun`` — заголовок карточки,
#: ``genitive`` — «Открыть карточку {genitive}», ``icon`` — бейдж в списке.
VENUE_TYPES: tuple[Mapping[str, str], ...] = (
    {"key": VENUE_TYPE_ARENA, "chip": "Арена", "noun": "Арена", "genitive": "арены", "icon": "❄️"},
    {"key": VENUE_TYPE_GYM, "chip": "Спортзал", "noun": "Спортзал", "genitive": "спортзала", "icon": "🏋️"},
    {
        "key": VENUE_TYPE_ROLLER,
        "chip": "Роллердром",
        "noun": "Роллердром",
        "genitive": "роллердрома",
        "icon": "🛼",
    },
    {
        "key": VENUE_TYPE_OUTDOOR,
        "chip": "Улица",
        "noun": "Открытая площадка",
        "genitive": "площадки",
        "icon": "🌳",
    },
    {"key": VENUE_TYPE_OTHER, "chip": "Другое", "noun": "Площадка", "genitive": "места", "icon": "📍"},
)

VENUE_TYPE_KEYS: tuple[str, ...] = tuple(v["key"] for v in VENUE_TYPES)

_BY_KEY: dict[str, Mapping[str, str]] = {v["key"]: v for v in VENUE_TYPES}


def normalize_venue_type(value: Any) -> str:
    """Неизвестное или пустое значение — это ``arena``, а не ошибка.

    Тип приходит из формы тренера и из строк, созданных до появления колонки;
    уронить чтение каталога из-за незнакомого ключа мы не хотим ни в одном из
    этих случаев. Валидация ввода — на границе API (``VENUE_TYPE_KEYS``).
    """
    key = str(value or "").strip().lower()
    return key if key in _BY_KEY else DEFAULT_VENUE_TYPE


def venue_type_noun(value: Any) -> str:
    """«Арена» / «Спортзал» — подпись типа в карточке площадки."""
    return _BY_KEY[normalize_venue_type(value)]["noun"]


def venue_type_chip(value: Any) -> str:
    """«Арена» / «Спортзал» — короткая подпись для фильтра и бейджа."""
    return _BY_KEY[normalize_venue_type(value)]["chip"]


def venue_type_icon(value: Any) -> str:
    return _BY_KEY[normalize_venue_type(value)]["icon"]


def venue_card_cta(value: Any) -> str:
    """«Открыть карточку арены» / «…зала» — CTA в списке площадок."""
    return f"Открыть карточку {_BY_KEY[normalize_venue_type(value)]['genitive']}"


def venue_site_label(value: Any) -> str:
    """«Сайт арены» / «Сайт зала» — ссылка на оператора в карточке."""
    return f"Сайт {_BY_KEY[normalize_venue_type(value)]['genitive']}"


def venue_type_options() -> list[dict[str, str]]:
    """Список для селектора в Mini App и для админки."""
    return [dict(v) for v in VENUE_TYPES]
