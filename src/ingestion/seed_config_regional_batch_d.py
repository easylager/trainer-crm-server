"""Regional batch D job.config seeds — arenas 38/19/42/33. See .ai/parsers/*.md dossiers.

Parser keys below match the batch-D wiring table (not the draft keys inside the .ai/parsers/*.md
dossiers, which predate this batch and use a different naming convention: bobruiskarena_html_v1,
soligorsk_szk_html_v1, shklov_ocr_photo_v1, gomel_hockey_news_v1). A later integration step is
expected to reconcile the two.
"""
from __future__ import annotations

PARSER_KEY_BOBRUISK_ARENA = "bobruisk_arena_v1"
PARSER_KEY_SOLIGORSK_SZK = "soligorsk_szk_v1"
PARSER_KEY_SHKLOV_ARENA = "shklov_arena_v1"
PARSER_KEY_GOMEL_LDS = "gomel_lds_v1"

BOBRUISK_ARENA_CONFIG: dict = {
    "schedule_url": "https://bobruiskarena.by/raspisanie",
    "prices_url": "https://www.bobruiskarena.by/service/sport/massovye-kataniya",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "prices_already_minor": True,
    "requires_by_egress": False,
}

SOLIGORSK_SZK_CONFIG: dict = {
    "url": "http://www.szk.by/uslugi/massovoe-katanie",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

SHKLOV_ARENA_CONFIG: dict = {
    "index_url": "http://sportshklov.by/category/raspisania/",
    "prices_url": "http://sportshklov.by/uslugi/",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "title_contains": "массового катания",
    "fetch_scheme": "http",
    "prices_already_minor": True,
    "requires_by_egress": False,
}

GOMEL_LDS_CONFIG: dict = {
    "news_index_url": "https://gomel.hockey.by/news/",
    "title_contains": "Расписание массовых катаний",
    "timezone": "Europe/Minsk",
    "kind": "public_skate",
    "prices_already_minor": True,
    "requires_by_egress": False,
}
