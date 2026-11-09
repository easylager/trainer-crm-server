"""Parnas (arena_id=174): the parser reads the live Tilda HTML, not only the innerText capture."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_ru_pilot import ParnasArenaTextParser
from src.ingestion.types import ParserJob

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "data/fixtures/spb-parnas-arena-live"


def _job(fixture_dir: Path) -> ParserJob:
    spec = (ROOT / "data/parsers/spb-parnas-arena.md").read_text(encoding="utf-8")
    config = json.loads(re.search(r"```json\n(.*?)\n```", spec, re.S).group(1))
    return ParserJob(
        id=174,
        arena_id=174,
        parser_key="parnasarena_text_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime(2026, 11, 9, tzinfo=timezone.utc),
        last_run_at=None,
        config={**config, "run_date": "2026-11-09", "fixture_dir": str(fixture_dir)},
    )


@pytest.mark.asyncio
async def test_live_html_week_is_read() -> None:
    extraction = await ParnasArenaTextParser().extract(_job(LIVE))
    got = [(s.local_date, s.starts_at_local, s.ends_at_local) for s in extraction.slots]
    assert got == [
        ("2026-11-09", "11:45", "12:45"),
        ("2026-11-09", "13:00", "14:00"),
        ("2026-11-10", "11:30", "12:30"),
        ("2026-11-10", "12:45", "13:45"),
        ("2026-11-11", "11:45", "13:45"),
        ("2026-11-12", "11:30", "12:30"),
        ("2026-11-12", "12:45", "13:45"),
        ("2026-11-12", "21:30", "22:30"),
        ("2026-11-13", "11:45", "12:45"),
        ("2026-11-13", "13:00", "14:00"),
        ("2026-11-14", "16:30", "17:30"),
        ("2026-11-14", "17:45", "19:00"),
        ("2026-11-14", "20:30", "22:30"),
        ("2026-11-15", "16:30", "17:30"),
        ("2026-11-15", "17:45", "18:45"),
        ("2026-11-15", "19:00", "20:30"),
    ]
    assert {s.price_adult for s in extraction.slots} == {70000}


@pytest.mark.asyncio
async def test_page_without_schedule_heading_raises(tmp_path: Path) -> None:
    (tmp_path / "schedule.md").write_text("<div>Ледовый центр «Парнас»</div>", encoding="utf-8")
    with pytest.raises(ValueError, match="heading"):
        await ParnasArenaTextParser().extract(_job(tmp_path))
