"""Brest poster: the weekly picture becomes sessions; an unreadable one fails loudly."""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.ingestion import brest_poster
from src.ingestion.adapters_regional_batch_a import BrestLdsParser
from src.ingestion.seed_config_regional_batch_a import BREST_LDS_CONFIG
from src.ingestion.types import ParserJob

_FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "brest-poster"
_PAGE_URL = "https://brest.hockey.by/raspisanie-svobodnogo-kataniya/"


def _job(**extra) -> ParserJob:
    cfg = {**BREST_LDS_CONFIG, "fixture_dir": str(_FIX), "run_date": "2026-10-27", **extra}
    return ParserJob(
        id=1, arena_id=22, parser_key="brest_lds_v1", is_enabled=True, cadence="daily",
        next_run_at=datetime.now(timezone.utc), last_run_at=None, config=cfg, notes=None,
    )


def test_read_poster_dates_and_times():
    result = brest_poster.read_poster((_FIX / "poster.jpg").read_bytes(), date(2026, 10, 27))
    assert result == [
        (date(2026, 10, 26), "21:15"), (date(2026, 10, 28), "21:15"), (date(2026, 10, 29), "21:15"),
        (date(2026, 10, 30), "21:15"), (date(2026, 10, 31), "21:15"), (date(2026, 11, 1), "21:15"),
    ]


def test_read_poster_resolves_dates_against_the_run_date():
    # Read three days later the same picture still resolves to the dates printed on it.
    result = brest_poster.read_poster((_FIX / "poster.jpg").read_bytes(), date(2026, 10, 30))
    assert result[0][0] == date(2026, 10, 26) and result[-1][0] == date(2026, 11, 1)


def test_blank_picture_is_refused():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1080, 1350), (10, 30, 90)).save(buf, "PNG")
    with pytest.raises(brest_poster.PosterError):
        brest_poster.read_poster(buf.getvalue(), date(2026, 10, 27))


def test_find_poster_url():
    html = (_FIX / "prices.html").read_text(encoding="utf-8")
    assert brest_poster.find_poster_url(html, _PAGE_URL) == "https://brest.hockey.by/7x1350.png"
    with pytest.raises(brest_poster.PosterError):
        brest_poster.find_poster_url("<h1>x</h1><img width='100' src='/a.png'>", _PAGE_URL)


@pytest.mark.asyncio
async def test_parser_uses_poster_days_not_every_day():
    extraction = await BrestLdsParser().extract(_job())
    dates = [s.local_date for s in extraction.slots]
    assert dates == ["2026-10-26", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]
    assert "2026-10-27" not in dates  # no session that day on the poster
    first = extraction.slots[0]
    assert (first.starts_at_local, first.ends_at_local) == ("21:15", "22:00")
    assert extraction.schedule_basis == "live"
    assert first.price_adult is not None and first.price_child is not None


@pytest.mark.asyncio
async def test_poster_false_keeps_projection():
    extraction = await BrestLdsParser().extract(_job(poster=False))
    assert len(extraction.slots) == 7 and extraction.schedule_basis == "projected"


@pytest.mark.asyncio
async def test_unreadable_poster_fails_the_run(tmp_path):
    from PIL import Image

    (tmp_path / "prices.html").write_text((_FIX / "prices.html").read_text(encoding="utf-8"), encoding="utf-8")
    Image.new("RGB", (1080, 1350), (10, 30, 90)).save(tmp_path / "poster.jpg")
    with pytest.raises(RuntimeError, match="афиша Бреста"):
        await BrestLdsParser().extract(_job(fixture_dir=str(tmp_path)))
