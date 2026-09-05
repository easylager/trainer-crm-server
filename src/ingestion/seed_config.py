"""Minsk Arena saleframe/55 job.config (from .ai/parsers/minsk-arena.md)."""
from __future__ import annotations

PARSER_KEY_MINSK_ARENA = "minskarena_saleframe_v1"

MINSK_ARENA_SALEFRAME_CONFIG: dict = {
    "url": "https://saleframe.minskarena.by/service/55",
    "api_host": "https://abws.minskarena.by",
    "service_id": 55,
    "init_path": "/api/v3/frame/init",
    "init_query": {"seid": 55, "target": "saleframe", "lang": "ru"},
    "calendar_path": "/api/v1/frame/service/{service_id}/calendar",
    "events_path": "/api/v1/frame/service/{service_id}/events",
    "events_query": {
        "sort": "start",
        "expand": "prices",
        "fields": "id,start,end,quota",
        "target": "saleframe",
        "lang": "ru",
    },
    "timezone": "Europe/Minsk",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "adult_zone_id": 970,
    "child_zone_id": 971,
    "kind": "public_skate",
    "kind_allow_substrings": ["массовое катание"],
    "drop_item_name_substrings": ["заточка"],
    "requires_by_egress": False,
    "requires_auth": False,
}
