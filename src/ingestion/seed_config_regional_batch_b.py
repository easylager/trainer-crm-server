"""Regional BY ice parser batch B job.config drafts (from .ai/parsers/<slug>.md).

Covers: Гродно Тринити (arena 10), Гродно Неман (arena 11), Лида ЛДС (arena 37),
Новополоцк ЛДС (arena 30). See src/ingestion/adapters_regional_batch_b.py for the
matching IceParser subclasses. A later integration step wires these into the
scheduler registry / ice_parser_jobs seed rows.
"""
from __future__ import annotations

PARSER_KEY_GRODNO_TRINITI = "grodno_triniti_v1"
PARSER_KEY_GRODNO_NEMAN = "grodno_neman_v1"
PARSER_KEY_LIDA_LDS = "lida_lds_v1"
PARSER_KEY_NOVOPOLOTSK_LDS = "novopolotsk_lds_v1"


GRODNO_TRINITI_CONFIG: dict = {
    "url": "https://ice.triniti-grodno.by/",
    "api_url": "https://ice.triniti-grodno.by/api/ice.php",
    "prices_url": "https://ice.triniti-grodno.by/prajs.html",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "drop_if_adult_minor_gte": 2000,
    "age_note": "детский от 3 до 12 лет",
    "requires_by_egress": False,
    "requires_auth": False,
}


GRODNO_NEMAN_CONFIG: dict = {
    "news_index_url": "https://neman.hockey.by/news/sobytie/",
    "title_contains": "массовых катаний",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 60,
    "session_label": "лёд Пышки",
    "prices_already_minor": True,
    "widget_url": "https://hcneman.by/schedule/scheduleMK.html",
    "widget_encoding": "utf-16",
    "requires_by_egress": False,
    "requires_auth": False,
    "notes": (
        "Fragile V1: the club's dedicated scheduleMK.html widget is stale "
        "(frozen 2026-04-05, page footer says updated 2026-05-26) and is "
        "intentionally NOT used to generate slots. The live source is the "
        "freshest post on news_index_url whose title contains title_contains — "
        "this is best-effort weekly polling of a news feed, not a stable "
        "schedule API, and can legitimately go empty between posts."
    ),
}


LIDA_LDS_CONFIG: dict = {
    "prices_url": "https://hc-lida.by/услуги/массовое-катание",
    "empty_schedule_url": "https://hc-lida.by/осп-сдюшор/расписание-работы-ледовой-арены",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "age_note": "детский до 16 лет",
    "week_start": "2026-08-31",
    "horizon_days": 7,
    "weekday_schedule": {
        "0": [],
        "1": ["21:15"],
        "2": [],
        "3": [],
        "4": ["13:45", "21:15"],
        "5": ["17:00", "19:15", "20:45"],
        "6": ["11:00", "17:15", "18:45", "20:15"],
    },
    "requires_by_egress": False,
    "requires_auth": False,
    "notes": (
        "V1: session times are transcribed from the weekly JPG on prices_url — "
        "there is no HTML time grid and this parser does not OCR at runtime. "
        "weekday_schedule/week_start are fixed to the 2026-08-31..09-06 photo; "
        "a human must update both by hand each Monday when the photo changes. "
        "Prices are parsed live from the HTML, not hardcoded."
    ),
}


NOVOPOLOTSK_LDS_CONFIG: dict = {
    "url": "https://hchimik.hockey.by/mass-skating/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "weekday_adult_minor_fallback": 900,
    "weekend_adult_minor_fallback": 1000,
    "rental_minor_fallback": 600,
    "child_price_on_page": False,
    "drop_place_substrings": ["тренировочн"],
    "requires_by_egress": False,
    "requires_auth": False,
}
