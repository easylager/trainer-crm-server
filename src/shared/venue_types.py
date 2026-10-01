"""
Тип площадки: лёд — частный случай, а не синоним.

До этого модуля сущность ``arenas`` молча означала «каток», и допущение было
зашито в UI (снежинка в табе, «карточка катка», «Сайт катка»). Первый же тренер
не со льда — зал на Машерова, арена #201 — сломал его во всех местах разом.

Заметь: для фигуриста лёд + ОФП + хореография — это один тренировочный цикл,
а не три разных продукта. Так что это достройка домена, а не расширение.

Падежи держим здесь, а не в шаблонах: «карточка катка» → «карточка зала»
подставляется в одну строку копирайта, и склонять её в трёх местах руками —
верный способ получить «карточка зал».

Клиентская сторона своего словаря не держит: подписи (``venue_chip``,
``venue_noun``, ``venue_cta``) приезжают готовыми в ответах ``/api/public/*``.

Магазин (``shop``, TASK-146) — площадка другого рода: там не тренируются, туда
идут за коньками, заточкой и прокатом. Он живёт в той же таблице ради гео, фото
и модерации, но тренеру как место работы не предлагается
(``TRAINER_VENUE_TYPE_KEYS``) и в ленту «Где заниматься» сам не попадает —
только по явному фильтру (``DEFAULT_HIDDEN_VENUE_TYPES``).
"""
from __future__ import annotations

from typing import Any, Mapping

VENUE_TYPE_ICE = "ice"
VENUE_TYPE_GYM = "gym"
VENUE_TYPE_CHOREO = "choreo"
VENUE_TYPE_POOL = "pool"
VENUE_TYPE_OUTDOOR = "outdoor"
VENUE_TYPE_OTHER = "other"
VENUE_TYPE_SHOP = "shop"

DEFAULT_VENUE_TYPE = VENUE_TYPE_ICE

#: ``chip`` — фильтр в каталоге, ``noun`` — заголовок карточки,
#: ``genitive`` — «Открыть карточку {genitive}», ``icon`` — бейдж в списке.
VENUE_TYPES: tuple[Mapping[str, str], ...] = (
    {"key": VENUE_TYPE_ICE, "chip": "Лёд", "noun": "Каток", "genitive": "катка", "icon": "❄️"},
    {"key": VENUE_TYPE_GYM, "chip": "Зал", "noun": "Зал", "genitive": "зала", "icon": "🏋️"},
    {
        "key": VENUE_TYPE_CHOREO,
        "chip": "Хореография",
        "noun": "Хореографический зал",
        "genitive": "зала",
        "icon": "🩰",
    },
    {"key": VENUE_TYPE_POOL, "chip": "Бассейн", "noun": "Бассейн", "genitive": "бассейна", "icon": "🏊"},
    {
        "key": VENUE_TYPE_OUTDOOR,
        "chip": "Улица",
        "noun": "Открытая площадка",
        "genitive": "площадки",
        "icon": "🌳",
    },
    {"key": VENUE_TYPE_OTHER, "chip": "Другое", "noun": "Площадка", "genitive": "места", "icon": "📍"},
    {"key": VENUE_TYPE_SHOP, "chip": "Магазин", "noun": "Магазин", "genitive": "магазина", "icon": "🧰"},
)

VENUE_TYPE_KEYS: tuple[str, ...] = tuple(v["key"] for v in VENUE_TYPES)

#: Где можно тренироваться — и значит, что тренер может выбрать местом работы.
TRAINER_VENUE_TYPE_KEYS: tuple[str, ...] = tuple(k for k in VENUE_TYPE_KEYS if k != VENUE_TYPE_SHOP)

#: Типы, которые лента каталога показывает только по явному фильтру. Магазин в
#: списке «где покататься» — шум для того, кто ищет лёд; но чип «Магазин» в
#: фасетах остаётся, чтобы до магазинов можно было дойти в один тап.
DEFAULT_HIDDEN_VENUE_TYPES: frozenset[str] = frozenset({VENUE_TYPE_SHOP})

_BY_KEY: dict[str, Mapping[str, str]] = {v["key"]: v for v in VENUE_TYPES}


def normalize_venue_type(value: Any) -> str:
    """Неизвестное или пустое значение — это ``ice``, а не ошибка.

    Тип приходит из формы тренера и из строк, созданных до появления колонки;
    уронить чтение каталога из-за незнакомого ключа мы не хотим ни в одном из
    этих случаев. Валидация ввода — на границе API (``VENUE_TYPE_KEYS``).
    """
    key = str(value or "").strip().lower()
    return key if key in _BY_KEY else DEFAULT_VENUE_TYPE


def venue_type_noun(value: Any) -> str:
    """«Каток» / «Зал» — подпись типа в карточке площадки."""
    return _BY_KEY[normalize_venue_type(value)]["noun"]


def venue_type_chip(value: Any) -> str:
    """«Лёд» / «Зал» — короткая подпись для фильтра и бейджа."""
    return _BY_KEY[normalize_venue_type(value)]["chip"]


def venue_type_icon(value: Any) -> str:
    return _BY_KEY[normalize_venue_type(value)]["icon"]


def venue_card_cta(value: Any) -> str:
    """«Открыть карточку катка» / «…зала» — CTA в списке площадок."""
    return f"Открыть карточку {_BY_KEY[normalize_venue_type(value)]['genitive']}"


def venue_site_label(value: Any) -> str:
    """«Сайт катка» / «Сайт зала» — ссылка на оператора в карточке."""
    return f"Сайт {_BY_KEY[normalize_venue_type(value)]['genitive']}"


def normalize_trainer_venue_type(value: Any) -> str:
    """Тип площадки, которую заводит тренер. Магазин тренеру недоступен — это лёд по умолчанию."""
    key = normalize_venue_type(value)
    return key if key in TRAINER_VENUE_TYPE_KEYS else DEFAULT_VENUE_TYPE


def venue_type_options(*, include_shop: bool = False) -> list[dict[str, str]]:
    """Список для селектора: тренеру — без магазина, админке — все типы."""
    return [dict(v) for v in VENUE_TYPES if include_shop or v["key"] != VENUE_TYPE_SHOP]
