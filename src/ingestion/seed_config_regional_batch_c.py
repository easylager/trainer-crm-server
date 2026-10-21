"""Batch C regional arenas job.config (from .ai/parsers/<slug>.md dossiers).

Arenas: vitebsk-ds (29), mogilev-ds (43), orsha-arena (31), gorki-lds (32),
ostrovets-lds (41), raubichi-rcop (15). Extract only — no ice_sessions writes, no DB access.
"""

from __future__ import annotations

PARSER_KEY_VITEBSK_DS = "vitebsk_ds_v1"
PARSER_KEY_MOGILEV_DS = "mogilev_ds_v1"
PARSER_KEY_ORSHA_ARENA = "orsha_arena_v1"
PARSER_KEY_GORKI_LDS = "gorki_lds_v1"
PARSER_KEY_OSTROVETS_LDS = "ostrovets_lds_v1"
PARSER_KEY_RAUBICHI = "raubichi_html_v1"


VITEBSK_DS_CONFIG: dict = {
    "schedule_api_url": (
        "https://api.24afisha.by/api/v2/schedule/events/1385106"
        "?cityId=11&lang=ru&slug=true&jsonld=0&ignoreEndTime=1"
    ),
    "afisha_event_id": 1385106,
    "afisha_city_id": 11,
    "afisha_object_id": 124,
    "afisha_event_url": (
        "https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta"
    ),
    "session_tickets_url": "https://saleframe.24afisha.by/?sid={session_id}&lang=ru",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 60,
    "age_note": (
        "детям до 3 лет не допускаются; 3–12 лет только с взрослым 18+ на "
        "коньках; на поздние сеансы несовершеннолетним — со законным представителем"
    ),
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
}

MOGILEV_DS_CONFIG: dict = {
    "schedule_url": "https://mogilev.hockey.by/raspisanie/",
    "prices_url": "https://mogilev.hockey.by/uslugi/?clear_cache=Y",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "kind_keep_substring": "массовое катание",
    "drop_label_substrings": [
        "СДЮШОР",
        "ХК «",
        'ХК "',
        "технолог",
        "заливка",
        "игра п-ва",
        "сотрудники",
    ],
    "default_duration_minutes": 45,
    "age_note": "детский до 6 лет",
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
}

ORSHA_ARENA_CONFIG: dict = {
    "schedule_url": "https://lokomotiv-orsha.by/%D1%80%D0%B0%D1%81%D0%BF%D0%B8%D1%81%D0%B0%D0%BD%D0%B8%D0%B5/",
    "prices_url": "https://lokomotiv-orsha.by/%D0%BF%D1%80%D0%B5%D0%B9%D1%81%D0%BA%D1%83%D1%80%D0%B0%D0%BD%D1%82/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "image_keep_prefix": "Ld-",
    "image_drop_prefixes": ["OL-", "Ol-"],
    "mk_label": "Массовое катание",
    "age_note": "детский младше 14 лет",
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
    # NOTE: this parser OCRs a JPG (no HTML slot grid exists). It needs
    # `pytesseract` (not in requirements.txt yet) plus the system `tesseract`
    # binary with the `rus` language pack on the worker host. See adapter
    # docstring / final report for details before wiring this into the
    # scheduler registry.
}

GORKI_LDS_CONFIG: dict = {
    "schedule_url": "https://gorkiled.by/",
    "prices_url": "http://gorkiled.by/ru/uslugi",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "mk_heading": "МАССОВОЕ КАТАНИЕ",
    "age_note": "детский до 16 лет",
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
}

OSTROVETS_LDS_CONFIG: dict = {
    "url": "https://sdushor-ostrovets.by/katanie-na-konkah/",
    "prices_url": "https://sdushor-ostrovets.by/prejskurant-cen/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "empty_cell_marker": "нет катаний",
    "age_note": "дети до 14 лет",
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
}

RAUBICHI_CONFIG: dict = {
    "url": "https://www.rau.by/skates/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "requires_by_egress": False,
    "requires_auth": False,
    "prices_already_minor": True,
}
