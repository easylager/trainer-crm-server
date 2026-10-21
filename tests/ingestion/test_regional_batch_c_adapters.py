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
    RaubichiHtmlParser,
    VitebskDsParser,
    _raubichi_schedule_slots,
    fetch_afisha_schedule,
    vitebsk_schedule_url,
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
    PARSER_KEY_RAUBICHI,
    PARSER_KEY_VITEBSK_DS,
    RAUBICHI_CONFIG,
    VITEBSK_DS_CONFIG,
)
from src.shared.schedule_basis import SCHEDULE_BASIS_LIVE
from src.ingestion.types import ParserJob
from tests.ingestion.tesseract_util import skip_unless_tesseract_rus

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"


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
    """24afisha schedule: day, start, 60 min, adult price, per-session buy link."""
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
    assert len(extraction.slots) == len(gold_sessions) == 3

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child is None
        assert slot.price_rental is None
        assert slot.external_url == gold["external_url"]
        assert slot.source_id == gold["source_id"]
        assert "массов" in slot.kind_raw.lower()

    friday = by_key[("2026-10-23", "22:00")]
    assert friday.ends_at_local == "23:00"
    assert friday.price_adult == 700


@pytest.mark.asyncio
async def test_vitebsk_replays_afisha_clearance_cookie(monkeypatch) -> None:
    """The first GET is an HTML verification page; the cookie unlocks the JSON."""
    seen: list[dict | None] = []

    async def fake_fetch(url: str, *, headers: dict | None = None) -> str:
        seen.append(headers)
        if len(seen) == 1:
            return '<html><script>document.cookie="hg-security=abc123; path=/; Secure"</script></html>'
        return '{"data":[]}'

    monkeypatch.setattr(
        "src.ingestion.adapters_regional_batch_c.fetch_http_text",
        fake_fetch,
    )
    payload = await fetch_afisha_schedule("https://api.24afisha.by/api/v2/schedule/events/1385106")
    assert payload == {"data": []}
    assert seen[1] is not None
    assert seen[1]["Cookie"] == "hg-security=abc123"


def test_vitebsk_schedule_url_ignores_stale_club_page() -> None:
    """Jobs seeded before the switch still store hockey.by in config.url."""
    url = vitebsk_schedule_url(
        {"url": "https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/?clear_cache=Y"}
    )
    assert url.startswith("https://api.24afisha.by/api/v2/schedule/events/1385106")
    assert "cityId=11" in url
    assert "ignoreEndTime=1" in url


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
    skip_unless_tesseract_rus()
    expected = _expected("orsha-arena")
    # OCR week headers are day+month only — anchor to fixture capture date so CI
    # calendar (e.g. October) does not shift inferred years and pick the wrong Ld-*.jpg.
    orsha_config = dict(ORSHA_ARENA_CONFIG)
    orsha_config["run_date"] = str(expected["captured_at"])[:10]
    job = _job(
        arena_id=31,
        parser_key=PARSER_KEY_ORSHA_ARENA,
        config=orsha_config,
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
    gorki_config = dict(GORKI_LDS_CONFIG)
    gorki_config["run_date"] = str(expected["captured_at"])[:10]
    job = _job(
        arena_id=32,
        parser_key=PARSER_KEY_GORKI_LDS,
        config=gorki_config,
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
    ostrovets_config = dict(OSTROVETS_LDS_CONFIG)
    ostrovets_config["run_date"] = str(expected["captured_at"])[:10]
    job = _job(
        arena_id=41,
        parser_key=PARSER_KEY_OSTROVETS_LDS,
        config=ostrovets_config,
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

    assert OSTROVETS_LDS_CONFIG.get("prices_already_minor") is True
    from datetime import datetime, timezone

    from src.ingestion.normalize import IceSessionNormalizer

    drafts = IceSessionNormalizer().normalize(extraction, job, now=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc))
    assert drafts
    assert drafts[0].price_adult_minor == 600
    assert drafts[0].price_child_minor == 400
    assert drafts[0].price_rental_minor == 500
    assert all(d.price_adult_minor == 600 for d in drafts)


@pytest.mark.asyncio
async def test_raubichi_matches_expected_fixture() -> None:
    expected = _expected("raubichi-rcop")
    job = _job(
        arena_id=15,
        parser_key=PARSER_KEY_RAUBICHI,
        config=dict(RAUBICHI_CONFIG),
        slug="raubichi-rcop",
        job_id=106,
    )
    extraction = await RaubichiHtmlParser().extract(job)
    gold_sessions = expected["sessions"]
    assert len(extraction.slots) == len(gold_sessions) == 4
    assert extraction.schedule_basis == SCHEDULE_BASIS_LIVE

    by_key = {(s.local_date, s.starts_at_local): s for s in extraction.slots}
    for gold in gold_sessions:
        slot = by_key[(gold["local_date"], gold["starts_at_local"])]
        assert slot.ends_at_local == gold["ends_at_local"]
        assert slot.price_adult == gold["price_adult_minor"]
        assert slot.price_child == gold["price_child_minor"]
        assert slot.price_rental == gold["price_rental_minor"]


def test_raubichi_closed_page_yields_no_slots() -> None:
    html = (_FIXTURES / "raubichi-rcop" / "skates-closed.html").read_text(encoding="utf-8")
    assert _raubichi_schedule_slots(html, duration_minutes=45) == []
