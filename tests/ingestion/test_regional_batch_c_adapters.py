"""Batch C regional parser adapters — fixture-driven extract() tests.

Mirrors the pattern in tests/ingestion/test_minsk_adapters.py: build a
ParserJob with config["fixture_dir"] pointing at .ai/data/fixtures/<slug>,
call parser.extract(job), assert against that fixture's expected.json.
No DB access, no normalize/publish — extract-only per the ingestion
contract (parsers never INSERT into ice_sessions).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestion.adapters_regional_batch_c import (
    GorkiLdsParser,
    MogilevDsParser,
    OrshaArenaParser,
    OstrovetsLdsParser,
    VitebskDsParser,
)
from src.ingestion.seed_config_regional_batch_c import (
    GORKI_LDS_CONFIG,
    MOGILEV_DS_CONFIG,
    ORSHA_ARENA_CONFIG,
    OSTROVETS_LDS_CONFIG,
    PARSER_KEY_GORKI_LDS,
    PARSER_KEY_MOGILEV_DS,
    PARSER_KEY_ORSHA_ARENA,
    PARSER_KEY_OSTROVETS_LDS,
    PARSER_KEY_VITEBSK_DS,
    VITEBSK_DS_CONFIG,
)
from src.ingestion.types import ParserJob

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / ".ai/data/fixtures"


def _job(*, arena_id: int, parser_key: str, config: dict, slug: str, job_id: int) -> ParserJob:
    cfg = dict(config)
    cfg["fixture_dir"] = str(_FIXTURES / slug)
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=None,  # not needed for extract()
        last_run_at=None,
        config=cfg,
    )


def _expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_vitebsk_ds_matches_expected_fixture() -> None:
    """AC: 7 slots, all public_skate, stale Apr/May 2026 grid preserved verbatim."""
    expected = _expected("vitebsk-ds")
    job = _job(
        arena_id=29,
        parser_key=PARSER_KEY_VITEBSK_DS,
        config=VITEBSK_DS_CONFIG,
        slug="vitebsk-ds",
        job_id=101,
    )
    extraction = await VitebskDsParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 7

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child is None
        assert slot.price_rental is None
        assert "массов" in slot.kind_raw.lower()

    # Spot-check the CMS typo fix (201:15 → 20:15) survives extraction.
    thursday = by_key[("2026-04-30", "20:15")]
    assert thursday.ends_at_local == "21:15"


@pytest.mark.asyncio
async def test_mogilev_ds_filters_school_and_hockey_rows() -> None:
    """AC: only 'массовое катание' rows become slots; СДЮШОР/ХК never leak."""
    expected = _expected("mogilev-ds")
    job = _job(
        arena_id=43,
        parser_key=PARSER_KEY_MOGILEV_DS,
        config=MOGILEV_DS_CONFIG,
        slug="mogilev-ds",
        job_id=102,
    )
    extraction = await MogilevDsParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 6

    assert not any("сдюшор" in s.kind_raw.lower() for s in extraction.slots)
    assert not any("хк" in s.kind_raw.lower() for s in extraction.slots)
    assert all("массов" in s.kind_raw.lower() for s in extraction.slots)

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child == gold["price_child_minor"]
        assert slot.price_rental == gold["price_rental_minor"]

    sample = by_key[("2026-09-04", "22:15")]
    assert sample.ends_at_local == "23:00"
    assert sample.price_adult == 800
    assert sample.price_child == 500
    assert sample.price_rental == 700


@pytest.mark.asyncio
async def test_orsha_arena_ocr_matches_expected_fixture() -> None:
    """AC: OCR of Ld-07-13.jpg yields exactly the 3 gold MK slots; OL/Ol dropped."""
    expected = _expected("orsha-arena")
    job = _job(
        arena_id=31,
        parser_key=PARSER_KEY_ORSHA_ARENA,
        config=ORSHA_ARENA_CONFIG,
        slug="orsha-arena",
        job_id=103,
    )
    extraction = await OrshaArenaParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 3

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child == gold["price_child_minor"]
        assert slot.price_rental == gold["price_rental_minor"]
        assert slot.session_label == "Массовое катание"

    assert ("2026-09-12", "21:00") in by_key
    assert ("2026-09-13", "14:45") in by_key
    assert ("2026-09-13", "20:00") in by_key
    # Only the newest published week (Ld-07-13) should be materialized —
    # the older Ld-31-06 week's Sat/Sun MK cells must not appear.
    assert ("2026-09-05", "20:45") not in by_key
    assert ("2026-09-06", "20:00") not in by_key


@pytest.mark.asyncio
async def test_gorki_lds_skips_cancelled_and_announcement_only_days() -> None:
    """AC: 4-5 Sep cancellation and 1 Sep bare announcement never become slots."""
    expected = _expected("gorki-lds")
    job = _job(
        arena_id=32,
        parser_key=PARSER_KEY_GORKI_LDS,
        config=GORKI_LDS_CONFIG,
        slug="gorki-lds",
        job_id=104,
    )
    extraction = await GorkiLdsParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 3

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child == gold["price_child_minor"]
        assert slot.price_rental == gold["price_rental_minor"]

    dates = {s.local_date for s in extraction.slots}
    assert "2026-09-04" not in dates
    assert "2026-09-05" not in dates
    assert "2026-09-01" not in dates


@pytest.mark.asyncio
async def test_ostrovets_lds_skips_no_session_cells() -> None:
    """AC: 'нет катаний' cells never become slots; 10 gold slots across 2 weeks."""
    expected = _expected("ostrovets-lds")
    job = _job(
        arena_id=41,
        parser_key=PARSER_KEY_OSTROVETS_LDS,
        config=OSTROVETS_LDS_CONFIG,
        slug="ostrovets-lds",
        job_id=105,
    )
    extraction = await OstrovetsLdsParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 10

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child == gold["price_child_minor"]
        assert slot.price_rental == gold["price_rental_minor"]

    sample = by_key[("2026-09-05", "15:45")]
    assert sample.ends_at_local == "16:30"
    assert sample.price_adult == 600
    assert sample.price_child == 400
    assert sample.price_rental == 500
