"""job.config for the batch-A regional BY ice parsers (Брест, Барановичи, Кобрин, Пинск).

Live URLs are from ``.ai/parsers/<slug>.md``. All four re-verified live on
2026-09-07 (see delivery report) — status noted per config below.
"""

from __future__ import annotations

PARSER_KEY_BREST_LDS = "brest_lds_v1"
PARSER_KEY_BARANOVICHI_LDS = "baranovichi_lds_v1"
PARSER_KEY_KOBRIN_LDS = "kobrin_lds_v1"
PARSER_KEY_PINSK_VOLNA = "pinsk_volna_v1"

# arena_id 22 — Брест, ул. Московская, 151. Weekly time grid is a JPEG photo,
# not HTML (see BrestLdsParser docstring): fixed_start/fixed_end/horizon_days
# are the config-carried substitute for OCR. Prices are parsed live.
BREST_LDS_CONFIG: dict = {
    "prices_url": "https://brest.hockey.by/raspisanie-svobodnogo-kataniya/",
    "schedule_url": "https://brest.hockey.by/raspisanie-svobodnogo-kataniya/raspisanie-ledovoy-areny/?clear_cache=Y",
    "timezone": "Europe/Minsk",
    "kind": "open_ice",
    "fixed_start": "21:15",
    "fixed_end": "22:15",
    "horizon_days": 7,
    "session_label": "СВ кат",
    "age_note": "детям до 12 лет",
    "prices_already_minor": True,
    "default_duration_minutes": 60,
    "requires_by_egress": False,
}

# arena_id 23 — Барановичи, Советский проспект, 20. Schedule table is real
# HTML; the price list is a scanned PDF with no text layer (verified with
# pymupdf), so price_*_minor are human-transcribed constants (see
# BaranovichiLdsParser docstring), not parsed at runtime.
BARANOVICHI_LDS_CONFIG: dict = {
    "schedule_url": "https://dvorec.by/?p=509",
    "prices_page_url": "https://dvorec.by/?p=85",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "duration_minutes": 45,
    "age_note": "дети до 14 лет",
    "price_adult_minor": 480,
    "price_child_minor": 360,
    "price_rental_minor": 500,
    "prices_already_minor": True,
    "default_duration_minutes": 45,
    "requires_by_egress": False,
}

# arena_id 25 — Кобрин, Замковая площадь 11А.
KOBRIN_LDS_CONFIG: dict = {
    "schedule_url": "https://kobrininform.by/afisha/ledovaya-arena/",
    "prices_url": "https://www.kobrincity.by/katalog/sport-i-fitnes/sportkompleksy/ledovaya-arena-g-kobrina.html",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "duration_minutes": 45,
    "age_note": "до 16 лет",
    "prices_already_minor": True,
    "default_duration_minutes": 45,
    "requires_by_egress": False,
}

# arena_id 24 — Пинск, ул. Иркутско-Пинской дивизии, 46 (УСК «Волна» / ПолесГУ).
PINSK_VOLNA_CONFIG: dict = {
    "schedule_url": "https://www.polessu.by/%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0-%D0%BF%D0%BE%D0%BB%D0%B5%D1%81%D0%B3%D1%83",
    "prices_url": "https://www.polessu.by/%D1%81%D0%BF%D0%BE%D1%80%D1%82%D0%BA%D0%BE%D0%BC%D0%BF%D0%BB%D0%B5%D0%BA%D1%81-%D0%BF%D0%BE%D0%BB%D0%B5%D1%81%D0%B3%D1%83-%D0%BB%D0%B5%D0%B4%D0%BE%D0%B2%D0%B0%D1%8F-%D0%B0%D1%80%D0%B5%D0%BD%D0%B0-0",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "age_note": "дошкольники, школьники и студенты дневной формы при предъявлении билета",
    "prices_already_minor": True,
    "default_duration_minutes": 45,
    "requires_by_egress": False,
}
