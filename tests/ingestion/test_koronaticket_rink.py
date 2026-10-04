"""Korona Ticket rink SSR parser (TASK-156)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.ingestion.koronaticket_rink import (
    enrich_zamok_slots,
    format_capacity_note,
    parse_rink_nuxt_html,
    remaining_seats,
)
from src.ingestion.types import ExtractedSlot

_FIXTURE = Path(__file__).resolve().parents[2] / "data/fixtures/minsk-zamok/korona-rink.html"


def test_remaining_seats_formula_matches_korona_ui() -> None:
    # 2026-10-04 13:15 on fixture: count=115, bought=40, locked=5, ordered=0 → 70
    assert remaining_seats(115, 40, 5, 0) == 70
    assert remaining_seats(115, 23, 2, 0) == 90


def test_parse_rink_nuxt_fixture() -> None:
    html = _FIXTURE.read_text(encoding="utf-8")
    sessions = parse_rink_nuxt_html(html)
    assert len(sessions) >= 10
    sample = next(s for s in sessions if s.starts_at_local == "13:15" and s.local_date == date(2026, 10, 4))
    assert sample.remaining == 70
    assert sample.ends_at_local == "14:00"


def test_format_capacity_note() -> None:
    assert format_capacity_note(12) == "12 мест"
    assert format_capacity_note(0) == "нет мест"


def test_enrich_zamok_slots_sets_capacity_note() -> None:
    html = _FIXTURE.read_text(encoding="utf-8")
    slots = [
        ExtractedSlot(
            local_date="2026-10-04",
            starts_at_local="13:15",
            kind_raw="Массовое катание",
            ends_at_local="14:00",
        )
    ]
    matched = enrich_zamok_slots(slots, html)
    assert matched == 1
    assert slots[0].capacity_note == "70 мест"


@pytest.mark.asyncio
async def test_zamok_adapter_enriches_from_korona_fixture() -> None:
    from datetime import datetime, timezone

    from src.ingestion.adapters import ZamokHtmlParser
    from src.ingestion.normalize import IceSessionNormalizer
    from src.ingestion.types import ParserJob
    from src.ingestion.validate import IceSessionValidator

    fixtures = _FIXTURE.parent
    job = ParserJob(
        id=2,
        arena_id=3,
        parser_key="zamok_html_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime(2026, 10, 4, 9, 0, tzinfo=timezone.utc),
        last_run_at=None,
        config={
            "url": "https://tczamok.by/entertainments/ice-rink",
            "timezone": "Europe/Minsk",
            "horizon_days": 1,
            "slot_start_suffix": ":15",
            "duration_minutes": 45,
            "run_date": "2026-10-04",
            "prices_already_minor": True,
            "fixture_dir": str(fixtures),
        },
    )
    ext = await ZamokHtmlParser().extract(job)
    now = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
    drafts = IceSessionValidator().validate(IceSessionNormalizer().normalize(ext, job, now=now))
    slot = next(d for d in drafts if d.starts_at_local.hour == 13 and d.starts_at_local.minute == 15)
    assert slot.capacity_note == "70 мест"
