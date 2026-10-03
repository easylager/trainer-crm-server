from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_minsk_by_egress import LedlifeOriginHtmlParser, is_by_origin_blocked_snapshot
from src.ingestion.parsers import default_registry
from dataclasses import replace

from src.ingestion.types import ParserJob

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures/minsk-ledlife"
_NOW = datetime(2025, 4, 21, 10, 0, tzinfo=timezone.utc)


def _job(**overrides) -> ParserJob:
    base = ParserJob(
        id=4,
        arena_id=4,
        parser_key=LedlifeOriginHtmlParser.parser_key,
        is_enabled=True,
        cadence="weekly",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config={
            "url": "https://ledlife.by/massovye_kataniya/",
            "prices_url": "https://ledlife.by/stoimost_uslug/",
            "timezone": "Europe/Minsk",
            "requires_by_egress": True,
            "fixture_dir": str(_FIXTURES),
        },
    )
    return replace(base, **overrides) if overrides else base


def test_ledlife_registered() -> None:
    assert isinstance(default_registry().get("ledlife_origin_html_v1"), LedlifeOriginHtmlParser)


def test_ledlife_403_fixture_blocked() -> None:
    html = (_FIXTURES / "massovye_kataniya-403.html").read_text(encoding="utf-8")
    assert is_by_origin_blocked_snapshot(html) is True


@pytest.mark.asyncio
async def test_ledlife_fixture_matches_golden() -> None:
    expected = json.loads((_FIXTURES / "expected.json").read_text(encoding="utf-8"))
    extraction = await LedlifeOriginHtmlParser().extract(_job())
    assert extraction.snapshot["blocked_without_by_egress"] is False
    assert len(extraction.slots) == len(expected["sessions"])
    assert expected["blocked_without_by_egress"] is False
    for slot, gold in zip(extraction.slots, expected["sessions"], strict=True):
        assert slot.price_adult == gold["price_adult_minor"] / 100
        assert slot.price_child == gold["price_child_minor"] / 100
        assert slot.age_note == gold["age_note"]


def test_ledlife_stoimost_day_and_evening_bands() -> None:
    from src.ingestion.adapters_minsk_by_egress import _ledlife_prices_from_stoimost

    html = (_FIXTURES / "stoimost_uslug.html").read_text(encoding="utf-8")
    book = _ledlife_prices_from_stoimost(html)
    assert book["day_45"] == {"adult": 650, "child": 450}
    assert book["evening_45"] == {"adult": 750, "child": 550}


@pytest.mark.asyncio
async def test_ledlife_live_capture_has_future_mass_slots(tmp_path: Path) -> None:
    """BY egress snapshot (2026-10): table parse + prices; at least one future MK row."""
    import shutil

    for name in ("massovye_kataniya-live.html", "stoimost_uslug-live.html"):
        shutil.copy(_FIXTURES / name, tmp_path / name.replace("-live", ""))
    base = _job()
    job = replace(base, config={**base.config, "fixture_dir": str(tmp_path)})
    extraction = await LedlifeOriginHtmlParser().extract(job)
    assert extraction.snapshot["blocked_without_by_egress"] is False
    assert len(extraction.slots) >= 3
    dates = {s.local_date for s in extraction.slots}
    assert "2026-10-04" in dates or "2026-10-10" in dates
