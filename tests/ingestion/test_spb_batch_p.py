"""SPb batch P ice parsers: СК «Гололёд» (arena_id=178), Айс Град (arena_id=188).

Fixtures are live ``curl`` snapshots of 2026-11-09 (see ``data/parsers/spb-gololed.md``);
``expected.json`` is the extract -> normalize -> validate result at 09:00 MSK that day.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_p import (
    AysGradHtmlParser,
    GololedHtmlParser,
    gololed_flat_price,
    gololed_public_prices,
)
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = ROOT / "data/fixtures/spb-gololed"
_NOW = datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc)

_CONFIG = {
    "url": "https://gololed.spb.ru/",
    "public_skate_url": "https://gololed.spb.ru/ledovaya-arena/massovye-kataniya",
    "hockey_url": "https://gololed.spb.ru/ledovaya-arena/chas-hokkeya",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "default_duration_minutes": 60,
    "requires_by_egress": False,
}


def _job(fixture_dir: Path) -> ParserJob:
    return ParserJob(
        id=501,
        arena_id=178,
        parser_key="gololed_html_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config={**_CONFIG, "fixture_dir": str(fixture_dir)},
    )


def _cell(*, slug: str, ts: int, label: str, end: str, session_id: str) -> str:
    return (
        f'<div class="schedule_td {slug} p-2" data-activity_slug="{slug}" data-start_date="{label}" '
        f'data-end_date="{end}" data-title="x" data-session_id="{session_id}" data-start_ts="{ts}"></div>'
    )


def _write_index(tmp_path: Path, body: str) -> Path:
    (tmp_path / "index.html").write_text(f'<div id="schedule_for_all_component">{body}</div>', encoding="utf-8")
    return tmp_path


async def _validated(job: ParserJob):
    extraction = await GololedHtmlParser().extract(job)
    return IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))


@pytest.mark.asyncio
async def test_gololed_matches_expected_snapshot() -> None:
    expected = json.loads((_FIXTURE / "expected.json").read_text(encoding="utf-8"))["sessions"]
    slots = await _validated(_job(_FIXTURE))

    assert len(slots) == len(expected) == 46
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected:
        slot = by_key[(date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))]
        assert slot.kind == gold["kind"]
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.source_id == gold["source_id"]


def test_gololed_prices_from_service_pages() -> None:
    public = gololed_public_prices((_FIXTURE / "massovye-kataniya.html").read_text(encoding="utf-8"))
    assert public == {60: 650, 75: 800}
    assert gololed_flat_price((_FIXTURE / "chas-hokkeya.html").read_text(encoding="utf-8")) == 650


@pytest.mark.asyncio
async def test_gololed_missing_price_pages_keep_slots(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text((_FIXTURE / "index.html").read_text(encoding="utf-8"), encoding="utf-8")
    slots = await _validated(_job(tmp_path))
    assert len(slots) == 46
    assert all(slot.price_adult_minor is None for slot in slots)


@pytest.mark.asyncio
async def test_gololed_layout_change_raises(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html><body>Сайт на обслуживании</body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="schedule_for_all_component"):
        await GololedHtmlParser().extract(_job(tmp_path))


@pytest.mark.asyncio
async def test_gololed_empty_widget_is_empty_schedule(tmp_path: Path) -> None:
    extraction = await GololedHtmlParser().extract(_job(_write_index(tmp_path, "")))
    assert extraction.slots == []


@pytest.mark.asyncio
async def test_gololed_drops_label_ts_mismatch_and_unknown_slugs(tmp_path: Path) -> None:
    # 1794208500 = 2026-11-09 10:15 MSK.
    body = "".join(
        (
            _cell(slug="massovoe_katanie", ts=1794208500, label="09 ноября 10:15", end="11:15", session_id="1"),
            _cell(slug="massovoe_katanie", ts=1794208500, label="09 ноября 10:15", end="11:15", session_id="1"),
            _cell(slug="massovoe_katanie", ts=1794208500, label="09 ноября 12:00", end="13:00", session_id="2"),
            _cell(slug="arenda_lda", ts=1794208500, label="09 ноября 10:15", end="11:15", session_id="3"),
            _cell(slug="chas_hokkeya", ts=1794208500, label="09 ноября 10:15", end="bad", session_id="4"),
        )
    )
    extraction = await GololedHtmlParser().extract(_job(_write_index(tmp_path, body)))
    assert [(s.local_date, s.starts_at_local, s.ends_at_local, s.source_id) for s in extraction.slots] == [
        ("2026-11-09", "10:15", "11:15", "gololed:1")
    ]


def test_gololed_registered() -> None:
    assert default_registry().get("gololed_html_v1") is not None


# --- Айс Град (arena_id=188) ---------------------------------------------------

_AYS_FIXTURE = ROOT / "data/fixtures/spb-ays-grad"
_AYS_CONFIG = {
    "url": "https://www.parkskazokspb.ru",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "default_duration_minutes": 60,
    "run_date": "2026-11-09",
    "requires_by_egress": False,
}

_AYS_PRICES = (
    '<div class="block" id="p1" style="top: 900px;">СО СВОИМИ КОНЬКАМИ 600 р./час за взрослый билет '
    "500 р./час за детский билет*</div>"
    '<div class="block" id="p2" style="top: 1000px;">ЦЕНА БИЛЕТА ЗА ВСЮ НОЧЬ КАТАНИЙ 800 руб. - со своими '
    "коньками 1150 руб. - с прокатом коньков</div>"
    '<div class="block" id="p3" style="top: 1100px;">ЧАС ХОККЕЯ - 600 руб.</div>'
)


def _ays_job(fixture_dir: Path) -> ParserJob:
    return ParserJob(
        id=502,
        arena_id=188,
        parser_key="aysgrad_html_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW,
        last_run_at=None,
        config={**_AYS_CONFIG, "fixture_dir": str(fixture_dir)},
    )


def _ays_page(tmp_path: Path, *days: tuple[int, str], prices: str = _AYS_PRICES) -> Path:
    blocks = [
        '<div class="block" id="h1" style="top: 3272px;">РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ</div>',
        '<div class="block" id="h2" style="top: 4881px;">ЧАС ХОККЕЯ - расписание</div>',
        prices,
    ]
    blocks += [f'<div class="block" id="d{i}" style="top: {top}px;">{text}</div>' for i, (top, text) in enumerate(days)]
    (tmp_path / "index.html").write_text("".join(blocks), encoding="utf-8")
    return tmp_path


async def _ays_validated(job: ParserJob):
    extraction = await AysGradHtmlParser().extract(job)
    return IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))


@pytest.mark.asyncio
async def test_ays_grad_matches_expected_snapshot() -> None:
    expected = json.loads((_AYS_FIXTURE / "expected.json").read_text(encoding="utf-8"))["sessions"]
    slots = await _ays_validated(_ays_job(_AYS_FIXTURE))

    assert len(slots) == len(expected) == 20
    got = [
        {
            "local_date": s.local_date.isoformat(),
            "starts_at_local": s.starts_at_local.strftime("%H:%M"),
            "ends_at_local": s.ends_at_local.strftime("%H:%M"),
            "kind": s.kind,
            "session_label": s.session_label,
            "price_adult_minor": s.price_adult_minor,
            "price_child_minor": s.price_child_minor,
            "price_rental_minor": s.price_rental_minor,
            "price_tiers": s.price_tiers,
            "age_note": s.age_note,
            "price_note": s.price_note,
        }
        for s in slots
    ]
    key = lambda row: (row["local_date"], row["starts_at_local"], row["kind"])  # noqa: E731
    assert sorted(got, key=key) == sorted(expected, key=key)


@pytest.mark.asyncio
async def test_ays_grad_windows_and_hockey_split_by_heading() -> None:
    slots = await _ays_validated(_ays_job(_AYS_FIXTURE))
    by_day = {(s.local_date.isoformat(), s.starts_at_local.strftime("%H:%M"), s.kind): s for s in slots}

    day = by_day[("2026-11-09", "11:45", "public_skate")]
    assert day.ends_at_local.strftime("%H:%M") == "16:30"
    assert (day.price_adult_minor, day.price_child_minor) == (60000, 50000)
    assert day.price_note == "Билет на 1 час, вход в любое время с 11:45 до 16:30"
    assert day.age_note == "Детский — до 12 лет"

    night = by_day[("2026-11-14", "23:30", "public_skate")]
    assert night.ends_at_utc - night.starts_at_utc == timedelta(hours=6)
    assert night.price_adult_minor == 80000
    assert night.price_tiers == [{"label": "С прокатом", "minor": 115000}]
    assert night.price_note == "Билет на всю ночь катаний, только в кассе катка"

    hockey = [s for s in slots if s.kind == "hockey_practice"]
    assert all(s.ends_at_utc - s.starts_at_utc == timedelta(hours=1) for s in hockey)
    assert all(s.price_adult_minor == 60000 for s in hockey)
    # 15 ноября у часа хоккея «НЕТ», а массовое катание есть.
    assert not any(s.local_date == date(2026, 11, 15) for s in hockey)
    assert ("2026-11-15", "13:00", "public_skate") in by_day


@pytest.mark.asyncio
async def test_ays_grad_missing_heading_raises(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<div class="block" id="h1" style="top: 10px;">РАСПИСАНИЕ МАССОВЫХ КАТАНИЙ</div>', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="headings"):
        await AysGradHtmlParser().extract(_ays_job(tmp_path))


@pytest.mark.asyncio
async def test_ays_grad_wrong_weekday_is_skipped(tmp_path: Path) -> None:
    page = _ays_page(
        tmp_path,
        (3336, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 11:45-16:30"),
        (3337, "10 НОЯБРЯ СРЕДА 11:45-16:30"),
    )
    extraction = await AysGradHtmlParser().extract(_ays_job(page))
    assert [s.local_date for s in extraction.slots] == ["2026-11-09"]


@pytest.mark.asyncio
async def test_ays_grad_duplicate_day_raises(tmp_path: Path) -> None:
    page = _ays_page(
        tmp_path,
        (3336, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 11:45-16:30"),
        (3337, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 12:00-16:30"),
    )
    with pytest.raises(ValueError, match="twice"):
        await AysGradHtmlParser().extract(_ays_job(page))


@pytest.mark.asyncio
async def test_ays_grad_block_far_below_heading_is_ignored(tmp_path: Path) -> None:
    page = _ays_page(tmp_path, (4000, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 11:45-16:30"))
    extraction = await AysGradHtmlParser().extract(_ays_job(page))
    assert extraction.slots == []


@pytest.mark.asyncio
async def test_ays_grad_window_without_hourly_price_is_not_published(tmp_path: Path) -> None:
    """Страница перестала писать «р./час» — окно 11:45–16:30 без пояснения не публикуется."""
    page = _ays_page(
        tmp_path,
        (3336, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 11:45-16:30"),
        (4940, "09 НОЯБРЯ ПОНЕДЕЛЬНИК 09:15-10:15"),
        prices='<div class="block" id="p3" style="top: 1100px;">ЧАС ХОККЕЯ - 600 руб.</div>',
    )
    slots = await _ays_validated(_ays_job(page))
    assert [(s.kind, s.starts_at_local.strftime("%H:%M")) for s in slots] == [("hockey_practice", "09:15")]


def test_ays_grad_registered() -> None:
    assert default_registry().get("aysgrad_html_v1") is not None
