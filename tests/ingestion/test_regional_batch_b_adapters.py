"""TASK: regional BY ice parser batch B — extract-only adapters vs fixture gold.

Covers arena 10 (Гродно Тринити), arena 11 (Гродно Неман), arena 37 (Лида ЛДС),
arena 30 (Новополоцк ЛДС). Each test builds a ParserJob pointing job.config at
the matching .ai/data/fixtures/<slug> dir, calls extract(), pushes the result
through the shared IceSessionNormalizer + IceSessionValidator (same pipeline as
tests/ingestion/test_minsk_adapters.py), and asserts the canonical drafts match
.ai/data/fixtures/<slug>/expected.json's sessions.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_regional_batch_b import (
    GrodnoNemanParser,
    GrodnoTrinitiParser,
    LidaLdsParser,
    NovopolotskLdsParser,
)
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.seed_config_regional_batch_b import (
    GRODNO_NEMAN_CONFIG,
    GRODNO_TRINITI_CONFIG,
    LIDA_LDS_CONFIG,
    NOVOPOLOTSK_LDS_CONFIG,
    PARSER_KEY_GRODNO_NEMAN,
    PARSER_KEY_GRODNO_TRINITI,
    PARSER_KEY_LIDA_LDS,
    PARSER_KEY_NOVOPOLOTSK_LDS,
)
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"


def _job(*, arena_id: int, parser_key: str, config: dict, next_run: datetime, job_id: int = 1) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=next_run,
        last_run_at=None,
        config=config,
    )


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


def _by_key(slots):
    return {(slot.local_date.isoformat(), slot.starts_at_local.strftime("%H:%M")): slot for slot in slots}


@pytest.mark.asyncio
async def test_grodno_triniti_matches_71_gold_sessions() -> None:
    expected = _load_expected("grodno-triniti")
    cfg = dict(GRODNO_TRINITI_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "grodno-triniti")
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    job = _job(arena_id=10, parser_key=PARSER_KEY_GRODNO_TRINITI, config=cfg, next_run=now - timedelta(minutes=5))

    extraction = await GrodnoTrinitiParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 71
    by_key = _by_key(slots)
    for gold in expected["sessions"]:
        key = (gold["local_date"], gold["starts_at_local"])
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor == gold["price_child_minor"]
        assert slot.price_rental_minor == gold["price_rental_minor"]

    # spot-check a weekday and a weekend-priced row explicitly
    sat = by_key[("2026-09-06", "11:00")]
    assert sat.price_adult_minor == 1100 and sat.price_child_minor == 900
    weekday = by_key[("2026-09-08", "11:00")]
    assert weekday.price_adult_minor == 900 and weekday.price_child_minor == 700
    assert all(slot.price_rental_minor == 800 for slot in slots)


@pytest.mark.asyncio
async def test_grodno_neman_news_post_yields_two_gold_sessions() -> None:
    expected = _load_expected("grodno-neman")
    cfg = dict(GRODNO_NEMAN_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "grodno-neman")
    now = datetime(2026, 9, 6, 10, 0, tzinfo=timezone.utc)
    job = _job(arena_id=11, parser_key=PARSER_KEY_GRODNO_NEMAN, config=cfg, next_run=now - timedelta(minutes=5))

    extraction = await GrodnoNemanParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 2
    by_key = _by_key(slots)
    for gold in expected["sessions"]:
        key = (gold["local_date"], gold["starts_at_local"])
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 1000
        assert slot.price_child_minor == gold["price_child_minor"] == 700
        assert slot.price_rental_minor == gold["price_rental_minor"] == 500
        assert slot.session_label == gold["session_label"] == "лёд Пышки"
    # widget-only April date must never surface
    assert not any(slot.local_date == date(2026, 4, 5) for slot in slots)


@pytest.mark.asyncio
async def test_lida_lds_photo_schedule_matches_10_gold_sessions() -> None:
    expected = _load_expected("lida-lds")
    cfg = dict(LIDA_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "lida-lds")
    now = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    job = _job(arena_id=37, parser_key=PARSER_KEY_LIDA_LDS, config=cfg, next_run=now - timedelta(minutes=5))

    extraction = await LidaLdsParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 10
    by_key = _by_key(slots)
    for gold in expected["sessions"]:
        key = (gold["local_date"], gold["starts_at_local"])
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 900
        assert slot.price_child_minor == gold["price_child_minor"] == 700
        assert slot.price_rental_minor == gold["price_rental_minor"] == 600
    # prices come from live HTML, not the 15/12 combo plaque on the photo
    assert all(slot.price_adult_minor != 1500 for slot in slots)


@pytest.mark.asyncio
async def test_novopolotsk_lds_table_matches_5_gold_sessions() -> None:
    expected = _load_expected("novopolotsk-lds")
    cfg = dict(NOVOPOLOTSK_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "novopolotsk-lds")
    now = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    job = _job(arena_id=30, parser_key=PARSER_KEY_NOVOPOLOTSK_LDS, config=cfg, next_run=now - timedelta(minutes=5))

    extraction = await NovopolotskLdsParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 5
    by_key = _by_key(slots)
    for gold in expected["sessions"]:
        key = (gold["local_date"], gold["starts_at_local"])
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert (slot.price_child_minor is None) == (gold["price_child_minor"] is None)
        assert slot.price_rental_minor == gold["price_rental_minor"] == 600
    # the malformed 06.09 15:00 row (место cell shifted into td-date) must still parse
    assert by_key[("2026-09-06", "15:00")].price_adult_minor == 1000
