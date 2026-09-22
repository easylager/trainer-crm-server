"""SPb batch J ice parser: СПб ГБУ СОК «Ижорец», ФОК «Ижорец» (arena_id=185).

Fixture + hand-extracted ``expected.json`` come from a direct ``curl`` of the
operator's own live page on 2026-09-22 (see ``data/parsers/spb-izhorets.md``).
This test runs the real extract -> normalize -> validate pipeline against the
captured fixture and checks the result against that ground truth — same
pattern as ``tests/ingestion/test_spb_batch_b.py``.

Currency is RUB and timezone is Europe/Moscow — the assertions below check
that explicitly, since ``IceSessionNormalizer`` silently falls back to
BYN/Europe/Minsk when a job.config omits those keys.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_j import IzhoretsHtmlParser
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"

_IZHORETS_CONFIG = {
    "url": "https://www.sok-izhorets.ru/massovoe-katanie-fok-izhorets",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "default_duration_minutes": 60,
    "week_start": "2026-09-22",
    "horizon_days": 7,
    "requires_by_egress": False,
}


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="weekly",
        next_run_at=datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc),
        last_run_at=None,
        config=config,
    )


def _izhorets_job() -> ParserJob:
    cfg = dict(_IZHORETS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-izhorets")
    return _job(arena_id=185, parser_key="izhorets_html_v1", config=cfg, job_id=401)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_izhorets_matches_expected_snapshot() -> None:
    job = _izhorets_job()
    expected = _load_expected("spb-izhorets")
    now = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    extraction = await IzhoretsHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 3
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] is None
        assert slot.price_child_minor == gold["price_child_minor"] is None
        assert slot.price_rental_minor == gold["price_rental_minor"] is None


@pytest.mark.asyncio
async def test_izhorets_weekday_only_times_read_as_separate_starts() -> None:
    """AC (spec item 2): "Воскресенье 13.00, 14:15" is two separate session
    starts (no "до"/dash range marker anywhere on the page), not a start/end
    pair — confirmed against the raw 2026-09-22 fixture text."""
    job = _izhorets_job()
    extraction = await IzhoretsHtmlParser().extract(job)
    starts = {(slot.local_date, slot.starts_at_local) for slot in extraction.slots}
    assert ("2026-09-27", "13:00") in starts
    assert ("2026-09-27", "14:15") in starts
    assert ("2026-09-26", "20:00") in starts
    assert len(extraction.slots) == 3


@pytest.mark.asyncio
async def test_izhorets_empty_schedule_block_is_valid_empty_state(tmp_path: Path) -> None:
    """If the operator ever clears the schedule paragraph down to nothing,
    that is a valid "nothing scheduled" state, not a parse failure — same
    convention as ``KupchinoArenaHtmlParser``'s empty text-block test."""
    empty_html = "<p><strong>Расписание сеансов:</strong></p><p><strong>Возможны изменения</strong></p>"
    fixture_dir = tmp_path / "spb-izhorets-empty"
    fixture_dir.mkdir()
    (fixture_dir / "massovoe-katanie.html").write_text(empty_html, encoding="utf-8")
    cfg = dict(_IZHORETS_CONFIG)
    cfg["fixture_dir"] = str(fixture_dir)
    job = _job(arena_id=185, parser_key="izhorets_html_v1", config=cfg, job_id=402)

    extraction = await IzhoretsHtmlParser().extract(job)

    assert extraction.slots == []


def test_izhorets_registered() -> None:
    registry = default_registry()
    assert registry.get("izhorets_html_v1") is not None
