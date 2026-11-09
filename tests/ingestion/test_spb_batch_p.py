"""SPb batch P ice parser: СК «Гололёд» (arena_id=178).

Fixtures are live ``curl`` snapshots of 2026-11-09 (see ``data/parsers/spb-gololed.md``);
``expected.json`` is the extract -> normalize -> validate result at 09:00 MSK that day.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_spb_batch_p import GololedHtmlParser, gololed_flat_price, gololed_public_prices
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
