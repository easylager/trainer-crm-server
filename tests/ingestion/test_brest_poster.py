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


# --- partial read (2026-11-03): one unreadable column no longer hides the whole week ---------------

_LIVE_NOV = _FIX / "poster-2026-11-03.jpg"  # brest.hockey.by poster for 03–08.11.2026


def test_read_poster_nov_week_reads_what_it_reads_correctly():
    # The vote is tesseract-version dependent: 5.5 (macOS) reads all five columns, 5.3 (Ubuntu CI and
    # Railway, apt) leaves «06.11» unread because «21:15» and «21:13» tie. What must hold on both:
    # at most that one column is skipped and nothing is ever read wrong.
    read = brest_poster.read_poster_detailed(_LIVE_NOV.read_bytes(), date(2026, 11, 3))
    assert read.unreadable <= 1
    assert len(read.sessions) + read.unreadable == 5
    assert set(read.sessions) <= {(date(2026, 11, d), "21:15") for d in (3, 5, 6, 7, 8)}


# Left edge of each column of the Nov poster -> its (day, month), so the publishing logic below is
# tested against a known read instead of whatever the installed tesseract makes of the picture.
_NOV_COLUMNS = {131: 3, 311: 5, 495: 6, 687: 7, 869: 8}


def _stub_columns(monkeypatch, skip: frozenset[int] = frozenset()):
    def fake(img, box):
        for x, day in _NOV_COLUMNS.items():
            if abs(box[0] - x) <= 20 and day not in skip:
                return (day, 11), (21, 15)
        return None

    monkeypatch.setattr(brest_poster, "_read_column", fake)


def test_one_unreadable_column_publishes_the_rest(monkeypatch):
    _stub_columns(monkeypatch, frozenset({7}))  # the 07.11 column fails
    read = brest_poster.read_poster_detailed(_LIVE_NOV.read_bytes(), date(2026, 11, 3))
    assert read.unreadable == 1
    assert [d.day for d, _ in read.sessions] == [3, 5, 6, 8]  # 07.11 absent, never a wrong day/time
    assert all(t == "21:15" for _, t in read.sessions)


def test_mostly_unreadable_poster_is_refused(monkeypatch):
    _stub_columns(monkeypatch, frozenset({3, 5, 6}))
    with pytest.raises(brest_poster.PosterError, match="неполное"):
        brest_poster.read_poster_detailed(_LIVE_NOV.read_bytes(), date(2026, 11, 3))


def test_date_far_from_run_date_is_refused():
    with pytest.raises(brest_poster.PosterError, match="далеко"):
        brest_poster.read_poster((_FIX / "poster.jpg").read_bytes(), date(2026, 10, 1))


@pytest.mark.asyncio
async def test_parser_publishes_readable_days_and_warns(monkeypatch, tmp_path, caplog):
    (tmp_path / "prices.html").write_text((_FIX / "prices.html").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "poster.jpg").write_bytes(_LIVE_NOV.read_bytes())
    _stub_columns(monkeypatch, frozenset({5}))
    with caplog.at_level("WARNING"):
        extraction = await BrestLdsParser().extract(_job(fixture_dir=str(tmp_path), run_date="2026-11-03"))
    assert [s.local_date for s in extraction.slots] == ["2026-11-03", "2026-11-06", "2026-11-07", "2026-11-08"]
    assert "unreadable" in caplog.text
    # 05.11 was not read: its published session must survive this run.
    assert extraction.replace_dates == frozenset(date(2026, 11, d) for d in (3, 6, 7, 8))


@pytest.mark.asyncio
async def test_whole_poster_replaces_its_full_date_range(monkeypatch, tmp_path):
    _stub_columns(monkeypatch)
    (tmp_path / "prices.html").write_text((_FIX / "prices.html").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "poster.jpg").write_bytes(_LIVE_NOV.read_bytes())
    extraction = await BrestLdsParser().extract(_job(fixture_dir=str(tmp_path), run_date="2026-11-03"))
    # 04.11 has no session on the poster: a stale one there is a cancelled session and goes.
    assert extraction.replace_dates == frozenset(date(2026, 11, d) for d in range(3, 9))
    assert {s.price_rental for s in extraction.slots} == {680}


@pytest.mark.asyncio
async def test_projection_without_poster_replaces_whole_window():
    extraction = await BrestLdsParser().extract(_job(poster=False))
    assert extraction.replace_dates is None
