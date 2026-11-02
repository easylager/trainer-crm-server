"""zhodino_sdyushor_v1: weekly WordPress tables on the Zhodino rink site (saved fixture)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from src.ingestion.adapters_regional_batch_d import ZhodinoSdyushorParser, _zhodino_schedule
from src.ingestion.parsers import default_registry
from src.ingestion.seed_config_regional_batch_d import PARSER_KEY_ZHODINO_SDYUSHOR, ZHODINO_SDYUSHOR_CONFIG
from src.ingestion.types import ParserJob

_FIXTURE = Path(__file__).resolve().parents[2] / "data/fixtures/zhodino-sdyushor"


def _job(fixture_dir: Path = _FIXTURE) -> ParserJob:
    cfg = dict(ZHODINO_SDYUSHOR_CONFIG)
    cfg["fixture_dir"] = str(fixture_dir)
    return ParserJob(
        id=1,
        arena_id=20,
        parser_key=PARSER_KEY_ZHODINO_SDYUSHOR,
        is_enabled=True,
        cadence="daily",
        next_run_at=None,
        last_run_at=None,
        config=cfg,
    )


@pytest.mark.asyncio
async def test_week_02_08_nov_matches_site() -> None:
    extraction = await ZhodinoSdyushorParser().extract(_job())
    by_day: dict[str, list[str]] = defaultdict(list)
    for s in extraction.slots:
        by_day[s.local_date].append(s.starts_at_local)
    week = {d: sorted(t) for d, t in by_day.items() if "2026-11-02" <= d <= "2026-11-08"}
    assert week == {
        "2026-11-02": ["18:00"],
        "2026-11-04": ["17:00", "18:30", "20:00"],
        "2026-11-06": ["17:00", "18:30", "20:00", "21:15"],
        "2026-11-07": ["14:00", "15:30", "17:00", "18:30", "20:00", "21:15"],
        "2026-11-08": ["14:00", "15:30", "17:00", "18:30", "20:00"],
    }


@pytest.mark.asyncio
async def test_previous_week_table_and_prices_duration() -> None:
    extraction = await ZhodinoSdyushorParser().extract(_job())
    prev = sorted((s.local_date, s.starts_at_local) for s in extraction.slots if s.local_date < "2026-11-02")
    assert prev == [
        ("2026-10-31", "14:00"), ("2026-10-31", "15:30"), ("2026-10-31", "17:00"),
        ("2026-10-31", "18:30"), ("2026-10-31", "20:00"), ("2026-10-31", "21:15"),
        ("2026-11-01", "14:00"), ("2026-11-01", "15:30"), ("2026-11-01", "17:00"),
        ("2026-11-01", "18:30"), ("2026-11-01", "20:00"),
    ]
    slot = next(s for s in extraction.slots if (s.local_date, s.starts_at_local) == ("2026-11-06", "21:15"))
    assert slot.ends_at_local == "22:00"  # «1 сеанс: 45 минут.» on the prices page
    assert (slot.price_adult, slot.price_child, slot.price_rental) == (650, 550, 490)
    assert slot.kind_raw == "Массовое катание"
    assert len(extraction.slots) == 30


def test_tables_without_dated_header_are_ignored() -> None:
    html = "<table><tr><td style='background:#0ff'></td><td>- сеансы массовых катаний</td></tr></table>"
    html += "<table><tr><td>Дата</td><td>Время работы</td></tr><tr><td>10.00</td><td>12.00</td></tr></table>"
    assert _zhodino_schedule(html) == []


@pytest.mark.asyncio
async def test_missing_prices_page_falls_back_to_config_duration(tmp_path: Path) -> None:
    (tmp_path / "raspisanie.html").write_text((_FIXTURE / "raspisanie.html").read_text("utf-8"), "utf-8")
    extraction = await ZhodinoSdyushorParser().extract(_job(tmp_path))
    assert extraction.slots
    assert all(s.price_adult is None for s in extraction.slots)
    assert extraction.slots[0].ends_at_local == "14:45"


def test_registered() -> None:
    assert default_registry().get(PARSER_KEY_ZHODINO_SDYUSHOR) is not None


@pytest.mark.asyncio
async def test_matches_expected_json() -> None:
    import json

    expected = json.loads((_FIXTURE / "expected.json").read_text("utf-8"))
    extraction = await ZhodinoSdyushorParser().extract(_job())
    got = [(s.local_date, s.starts_at_local, s.ends_at_local, s.price_adult) for s in extraction.slots]
    gold = [
        (g["local_date"], g["starts_at_local"], g["ends_at_local"], g["price_adult_minor"])
        for g in expected["sessions"]
    ]
    assert got == gold
