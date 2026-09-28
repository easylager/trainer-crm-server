"""SPb batch O ice parser: Шуваловский лёд (arena_id=196).

Fixture + hand-derived ``expected.json`` come from a real ``/shedule/`` page
capture on 2026-09-22 (via the r.jina.ai reader-proxy, direct TLS to
shuvalov-ice.ru having timed out from this research sandbox — see
``data/parsers/spb-shuvalovsky-led.md``). This test runs the real
extract -> normalize -> validate pipeline against the captured fixture and
checks the result against that ground truth — same pattern as
``tests/ingestion/test_spb_batch_b.py``.

Currency is RUB and timezone is Europe/Moscow — the assertions below check
that explicitly, since ``IceSessionNormalizer`` silently falls back to
BYN/Europe/Minsk when a job.config omits those keys.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_o import ShuvalovskyLedHtmlParser
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"

_SHUVALOVSKY_LED_CONFIG = {
    "url": "https://shuvalov-ice.ru/shedule/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "prices_already_minor": True,
    "run_year": 2026,
    "price_60min_weekday_minor": 70000,
    "price_60min_weekend_minor": 80000,
    "price_75min_weekday_minor": 87500,
    "price_75min_weekend_minor": 100000,
    "price_rental_minor": 60000,
    "requires_by_egress": False,
}


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
        last_run_at=None,
        config=config,
    )


def _shuvalovsky_led_job() -> ParserJob:
    cfg = dict(_SHUVALOVSKY_LED_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-shuvalovsky-led")
    return _job(arena_id=196, parser_key="shuvalovskyled_html_v1", config=cfg, job_id=303)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_shuvalovsky_led_matches_expected_snapshot() -> None:
    job = _shuvalovsky_led_job()
    expected = _load_expected("spb-shuvalovsky-led")
    now = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    extraction = await ShuvalovskyLedHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    # The raw extraction carries the fixture's full current-week grid (all 7
    # days, including 2026-09-21 which is already in the past relative to
    # `now` above); normalize's drop_past rule removes anything whose
    # ends_at_utc is already behind `now`, per this project's canon (README
    # "не выдумывать сетку" section) — so only 2026-09-21's 2 sessions are
    # dropped here, leaving 30 validated slots.
    assert len(extraction.slots) == len(expected["sessions"]) == 32
    future_sessions = [s for s in expected["sessions"] if s["local_date"] != "2026-09-21"]
    assert len(future_sessions) == len(slots) == 30

    by_key = {}
    for slot in slots:
        by_key.setdefault((slot.local_date, slot.starts_at_local), []).append(slot)

    for gold in future_sessions:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        candidates = by_key.get(key)
        assert candidates, f"missing slot for {key}"
        # Both rinks can share the exact same start time on other weeks; the
        # 2026-09-22 fixture never does, so exactly one candidate per key
        # here — but match by session_label to stay correct if that changes.
        matches = [s for s in candidates if (s.session_label or None) == gold["session_label"]]
        assert len(matches) == 1, f"expected exactly one match for {key} / {gold['session_label']}"
        slot = matches[0]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor == gold["price_child_minor"]
        assert slot.price_rental_minor == gold["price_rental_minor"] == 60000


@pytest.mark.asyncio
async def test_shuvalovsky_led_duration_drives_price_tier() -> None:
    """AC (spec item 4): a 60-minute session prices differently from a
    75-minute one, and weekday differs from weekend — not a single flat
    price for the whole page."""
    job = _shuvalovsky_led_job()
    extraction = await ShuvalovskyLedHtmlParser().extract(job)

    # 2026-09-22 (Tuesday, weekday) 19:00-20:15 Малый лед = 75 min -> weekday 75-tier.
    tue_75 = next(
        s
        for s in extraction.slots
        if s.local_date == "2026-09-22" and s.starts_at_local == "19:00"
    )
    assert tue_75.price_adult == 87500

    # 2026-09-26 (Saturday, weekend) 19:00-20:00 Большой лед = 60 min -> weekend 60-tier.
    sat_60 = next(
        s
        for s in extraction.slots
        if s.local_date == "2026-09-26" and s.starts_at_local == "19:00"
    )
    assert sat_60.price_adult == 80000


@pytest.mark.asyncio
async def test_shuvalovsky_led_ignores_unexplained_trailing_markers() -> None:
    """AC (spec Blockers note): the source glues unexplained trailing
    characters ("*", "**", a stray "Ю") straight onto some end times with no
    legend anywhere on the page — they must not corrupt the parsed time or
    suppress the slot."""
    job = _shuvalovsky_led_job()
    extraction = await ShuvalovskyLedHtmlParser().extract(job)

    stray_glyph = next(
        s
        for s in extraction.slots
        if s.local_date == "2026-09-27" and s.starts_at_local == "14:00"
    )
    assert stray_glyph.ends_at_local == "15:00"

    double_marker = next(
        s
        for s in extraction.slots
        if s.local_date == "2026-09-26" and s.starts_at_local == "21:15"
    )
    assert double_marker.ends_at_local == "22:15"


def test_shuvalovsky_led_registered() -> None:
    registry = default_registry()
    assert registry.get("shuvalovskyled_html_v1") is not None
