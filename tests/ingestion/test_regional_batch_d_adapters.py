"""Batch D regional parser adapters (arenas 38/19/42/33). Extract only, fixture-driven."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_regional_batch_d import (
    BobruiskArenaParser,
    GomelLdsParser,
    ShklovArenaParser,
    SoligorskSzkParser,
)
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.seed_config_regional_batch_d import (
    BOBRUISK_ARENA_CONFIG,
    GOMEL_LDS_CONFIG,
    PARSER_KEY_BOBRUISK_ARENA,
    PARSER_KEY_GOMEL_LDS,
    PARSER_KEY_SHKLOV_ARENA,
    PARSER_KEY_SOLIGORSK_SZK,
    SHKLOV_ARENA_CONFIG,
    SOLIGORSK_SZK_CONFIG,
)
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / ".ai/data/fixtures"
_NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config=config,
    )


def _bobruisk_job() -> ParserJob:
    cfg = dict(BOBRUISK_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "bobruisk-arena")
    cfg["run_year"] = 2026
    return _job(arena_id=38, parser_key=PARSER_KEY_BOBRUISK_ARENA, config=cfg, job_id=101)


def _soligorsk_job() -> ParserJob:
    cfg = dict(SOLIGORSK_SZK_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "soligorsk-szk")
    cfg["run_year"] = 2026
    return _job(arena_id=19, parser_key=PARSER_KEY_SOLIGORSK_SZK, config=cfg, job_id=102)


def _shklov_job() -> ParserJob:
    cfg = dict(SHKLOV_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "shklov-arena")
    return _job(arena_id=42, parser_key=PARSER_KEY_SHKLOV_ARENA, config=cfg, job_id=103)


def _gomel_job() -> ParserJob:
    cfg = dict(GOMEL_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "gomel-lds")
    return _job(arena_id=33, parser_key=PARSER_KEY_GOMEL_LDS, config=cfg, job_id=104)


def _validated(extraction, job):
    return IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))


@pytest.mark.asyncio
async def test_bobruisk_arena_matches_expected_fixture() -> None:
    expected = json.loads((_FIXTURES / "bobruisk-arena/expected.json").read_text(encoding="utf-8"))
    job = _bobruisk_job()
    extraction = await BobruiskArenaParser().extract(job)
    slots = _validated(extraction, job)

    assert len(slots) == len(expected["sessions"]) == 15
    assert all(slot.kind == "public_skate" for slot in slots)
    assert all(slot.price_child_minor is None for slot in slots)

    by_key = {(s.local_date, s.starts_at_local.strftime("%H:%M")): s for s in slots}
    for gold in expected["sessions"]:
        hit = by_key[(date.fromisoformat(gold["local_date"]), gold["starts_at_local"])]
        assert hit.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert hit.price_adult_minor == gold["price_adult_minor"]
        assert hit.price_rental_minor == gold["price_rental_minor"]

    # weekend row: Saturday 12 Sept has no header in the source (SPEC gotcha) — must not be dropped
    sat12 = [s for s in slots if s.local_date == date(2026, 9, 12)]
    assert {s.starts_at_local for s in sat12} == {time(19, 15), time(20, 30), time(21, 45)}
    assert all(s.price_adult_minor == 700 for s in sat12)  # weekend price, not weekday 550


@pytest.mark.asyncio
async def test_soligorsk_szk_matches_expected_fixture_and_handles_midnight_crossing() -> None:
    expected = json.loads((_FIXTURES / "soligorsk-szk/expected.json").read_text(encoding="utf-8"))
    job = _soligorsk_job()
    extraction = await SoligorskSzkParser().extract(job)
    slots = _validated(extraction, job)

    assert len(slots) == len(expected["sessions"]) == 11
    assert all(slot.kind == "public_skate" for slot in slots)
    assert all(slot.age_note == "детский до 16 лет" for slot in slots)

    by_key = {(s.local_date, s.starts_at_local.strftime("%H:%M")): s for s in slots}
    for gold in expected["sessions"]:
        hit = by_key[(date.fromisoformat(gold["local_date"]), gold["starts_at_local"])]
        assert hit.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert hit.price_adult_minor == gold["price_adult_minor"]
        assert hit.price_child_minor == gold["price_child_minor"]
        assert hit.price_rental_minor == gold["price_rental_minor"]
        assert hit.session_label == gold["session_label"]

    # AC: 23:00-00:00 night session — must not be dropped or mis-dated across midnight.
    night = by_key[(date(2026, 9, 5), "23:00")]
    assert night.local_date == date(2026, 9, 5)
    assert night.ends_at_local == time(0, 0)
    assert night.session_label == "Рок-хиты"
    assert (night.ends_at_utc - night.starts_at_utc).total_seconds() == 3600


@pytest.mark.asyncio
async def test_shklov_arena_ocr_matches_expected_fixture() -> None:
    expected = json.loads((_FIXTURES / "shklov-arena/expected.json").read_text(encoding="utf-8"))
    job = _shklov_job()
    extraction = await ShklovArenaParser().extract(job)
    slots = _validated(extraction, job)

    assert len(slots) == len(expected["sessions"]) == 16
    assert all(slot.kind == "public_skate" for slot in slots)
    assert all(slot.price_adult_minor == 510 for slot in slots)
    assert all(slot.price_child_minor == 420 for slot in slots)
    assert all(slot.price_rental_minor == 420 for slot in slots)

    by_key = {(s.local_date, s.starts_at_local.strftime("%H:%M")): s for s in slots}
    for gold in expected["sessions"]:
        hit = by_key[(date.fromisoformat(gold["local_date"]), gold["starts_at_local"])]
        assert hit.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]

    # Monday 31 Aug is not on the poster — must not be invented.
    assert all(s.local_date != date(2026, 8, 31) for s in slots)
    # Sat/Sun get the 4-session grid, weekdays only 2.
    sat = [s for s in slots if s.local_date == date(2026, 9, 5)]
    assert len(sat) == 4


@pytest.mark.asyncio
async def test_gomel_lds_matches_expected_fixture() -> None:
    expected = json.loads((_FIXTURES / "gomel-lds/expected.json").read_text(encoding="utf-8"))
    job = _gomel_job()
    extraction = await GomelLdsParser().extract(job)
    slots = _validated(extraction, job)

    assert len(slots) == len(expected["sessions"]) == 7
    assert all(slot.kind == "public_skate" for slot in slots)
    assert all(slot.price_child_minor is None for slot in slots)
    assert all(slot.price_rental_minor == 500 for slot in slots)
    assert all(slot.age_note == "детям до 10 лет вход после 21:00 запрещен" for slot in slots)

    by_key = {(s.local_date, s.starts_at_local.strftime("%H:%M")): s for s in slots}
    for gold in expected["sessions"]:
        hit = by_key[(date.fromisoformat(gold["local_date"]), gold["starts_at_local"])]
        assert hit.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert hit.price_adult_minor == gold["price_adult_minor"]

    # Friday counts toward the weekend (пт-вс) price bucket on this site.
    fri = by_key[(date(2026, 9, 4), "20:00")]
    assert fri.price_adult_minor == 1200
    thu = by_key[(date(2026, 9, 3), "19:00")]
    assert thu.price_adult_minor == 1000
