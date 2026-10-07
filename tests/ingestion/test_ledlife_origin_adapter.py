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
            "prices_detail_url": "https://ledlife.by/krytyi_katok434451/",
            "mk_price_bands": {
                "day_45": {"adult": 1000, "child": 800},
                "evening_45": {"adult": 1100, "child": 900},
            },
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
    assert expected["blocked_without_by_egress"] is False
    mk_slots = [s for s in extraction.slots if s.kind_raw != "hockey_practice"]
    gold_mk = [s for s in expected["sessions"] if s["kind"] == "public_skate"]
    assert len(mk_slots) == len(gold_mk)
    for slot, gold in zip(mk_slots, gold_mk, strict=True):
        assert slot.price_adult == gold["price_adult_minor"] / 100
        assert slot.price_child == gold["price_child_minor"] / 100
        assert slot.age_note == gold["age_note"]


@pytest.mark.asyncio
async def test_ledlife_fixture_includes_ohm_rows() -> None:
    extraction = await LedlifeOriginHtmlParser().extract(_job())
    ohm = [s for s in extraction.slots if s.kind_raw == "hockey_practice"]
    assert len(ohm) == 9
    assert all(s.price_adult is not None for s in ohm)


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
    shutil.copy(_FIXTURES / "krytyi_katok434451.html", tmp_path / "krytyi_katok434451.html")
    base = _job()
    job = replace(
        base,
        config={
            **base.config,
            "fixture_dir": str(tmp_path),
            "mk_rental_minor": 700,
        },
    )
    extraction = await LedlifeOriginHtmlParser().extract(job)
    assert extraction.snapshot["blocked_without_by_egress"] is False
    mk_slots = [s for s in extraction.slots if s.kind_raw != "hockey_practice"]
    assert len(mk_slots) >= 3
    dates = {s.local_date for s in mk_slots}
    assert "2026-10-04" in dates or "2026-10-10" in dates
    assert all(s.price_adult is not None and s.price_child is not None for s in mk_slots)
    assert mk_slots[0].price_adult == 11.0  # evening/weekend band, BYN with VAT
    assert mk_slots[0].price_rental == 7.0


def test_ledlife_preiskurant_page_uses_mk_bands() -> None:
    from src.ingestion.adapters_minsk_by_egress import _ledlife_prices_from_stoimost

    html = (_FIXTURES / "krytyi_katok434451.html").read_text(encoding="utf-8")
    job = _job()
    book = _ledlife_prices_from_stoimost(html, job)
    assert book["day_45"] == {"adult": 1000, "child": 800}
    assert book["evening_45"] == {"adult": 1100, "child": 900}
