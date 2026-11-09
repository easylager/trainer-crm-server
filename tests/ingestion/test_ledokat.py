"""Ledokat widget parsers: Арена Ракета (arena_id=171, Ledokat rink 1929)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_ledokat import RaketaLedokatParser, ledokat_week_url, raketa_prices
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data/fixtures/spb-arena-raketa"
NOW = datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc)
CONFIG = {
    "url": "https://ice-arenaraketa.ru/calender",
    "price_url": "https://ice-arenaraketa.ru/price",
    "widget_id": "352fe25daf686bdb4edca223c921acea",
    "rink_id": 1929,
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "default_duration_minutes": 60,
    "run_date": "2026-11-09",
}


def _job(fixture_dir: Path) -> ParserJob:
    return ParserJob(
        id=171,
        arena_id=171,
        parser_key="raketa_ledokat_v1",
        is_enabled=True,
        cadence="daily",
        next_run_at=NOW,
        last_run_at=None,
        config={**CONFIG, "fixture_dir": str(fixture_dir)},
    )


def _seance(seance_id: int, service: str | None, start: str, end: str, name: str = "") -> dict:
    return {
        "placeName": "Арена",
        "seanceId": seance_id,
        "seanceName": name,
        "service": service,
        "tickets": [],
        "startedAt": start,
        "finishedAt": end,
    }


def _week(tmp_path: Path, seances: list[dict], *, rink_id: int = 1929, price: bool = True) -> Path:
    body = {"error": False, "payload": {"widget": {"rinkId": rink_id, "rinkName": "X"}, "seances": seances}}
    (tmp_path / "seances-0.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    if price:
        (tmp_path / "price.html").write_text((FIXTURE / "price.html").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


async def _validated(job: ParserJob):
    extraction = await RaketaLedokatParser().extract(job)
    return IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=NOW))


@pytest.mark.asyncio
async def test_raketa_matches_expected_snapshot() -> None:
    expected = json.loads((FIXTURE / "expected.json").read_text(encoding="utf-8"))["sessions"]
    slots = await _validated(_job(FIXTURE))
    got = [
        {
            "local_date": s.local_date.isoformat(),
            "starts_at_local": s.starts_at_local.strftime("%H:%M"),
            "ends_at_local": s.ends_at_local.strftime("%H:%M"),
            "kind": s.kind,
            "price_adult_minor": s.price_adult_minor,
            "price_child_minor": s.price_child_minor,
            "price_rental_minor": s.price_rental_minor,
            "age_note": s.age_note,
            "source_id": s.source_id,
        }
        for s in slots
    ]
    assert len(got) == len(expected) == 61
    key = lambda row: (row["local_date"], row["starts_at_local"], row["kind"])  # noqa: E731
    assert sorted(got, key=key) == sorted(expected, key=key)


def test_raketa_price_table() -> None:
    prices = raketa_prices((FIXTURE / "price.html").read_text(encoding="utf-8"))
    assert prices == {"adult": 450, "child": 400, "rental": 350, "hockey": 550}
    assert raketa_prices(None) == {"adult": None, "child": None, "rental": None, "hockey": None}


@pytest.mark.asyncio
async def test_only_known_services_become_slots(tmp_path: Path) -> None:
    page = _week(
        tmp_path,
        [
            _seance(1, "Массовое катание", "2026-11-09 13:15:00", "2026-11-09 14:15:00"),
            _seance(2, "Массовое катание FREE", "2026-11-09 12:00:00", "2026-11-09 13:00:00"),
            _seance(3, None, "2026-11-09 15:00:00", "2026-11-09 16:00:00", name="АРЕНДА"),
            _seance(4, "Час хоккея", "2026-11-09 08:15:00", "2026-11-09 09:15:00"),
            _seance(5, "Фигурное катание", "2026-11-09 17:00:00", "2026-11-09 18:00:00"),
        ],
    )
    extraction = await RaketaLedokatParser().extract(_job(page))
    assert sorted((s.source_id, s.kind_raw) for s in extraction.slots) == [
        ("ledokat:1", "public_skate"),
        ("ledokat:4", "hockey_practice"),
    ]


@pytest.mark.asyncio
async def test_foreign_rink_widget_raises(tmp_path: Path) -> None:
    page = _week(tmp_path, [_seance(1, "Массовое катание", "2026-11-09 13:15:00", "2026-11-09 14:15:00")], rink_id=719)
    with pytest.raises(ValueError, match="rink 719"):
        await RaketaLedokatParser().extract(_job(page))


@pytest.mark.asyncio
async def test_error_answer_raises(tmp_path: Path) -> None:
    (tmp_path / "seances-0.json").write_text('{"error": true, "message": "not found"}', encoding="utf-8")
    with pytest.raises(ValueError, match="error"):
        await RaketaLedokatParser().extract(_job(tmp_path))


@pytest.mark.asyncio
async def test_bad_times_and_duplicates_are_dropped(tmp_path: Path) -> None:
    page = _week(
        tmp_path,
        [
            _seance(1, "Массовое катание", "2026-11-09 13:15:00", "2026-11-09 14:15:00"),
            _seance(1, "Массовое катание", "2026-11-09 13:15:00", "2026-11-09 14:15:00"),
            _seance(2, "Массовое катание", "2026-11-09 14:15:00", "2026-11-09 13:15:00"),
            _seance(3, "Массовое катание", "2026-11-09 23:30:00", "2026-11-10 00:30:00"),
            _seance(4, "Массовое катание", "09.11.2026 13:15", "09.11.2026 14:15"),
        ],
    )
    extraction = await RaketaLedokatParser().extract(_job(page))
    assert [s.source_id for s in extraction.slots] == ["ledokat:1"]


@pytest.mark.asyncio
async def test_missing_price_page_keeps_slots_without_price(tmp_path: Path) -> None:
    page = _week(tmp_path, [_seance(1, "Массовое катание", "2026-11-09 13:15:00", "2026-11-09 14:15:00")], price=False)
    slots = await _validated(_job(page))
    assert len(slots) == 1 and slots[0].price_adult_minor is None and slots[0].age_note is None


def test_week_url_is_monday_to_sunday() -> None:
    from datetime import date

    assert ledokat_week_url("abc", date(2026, 11, 9)).endswith("/abc?dateFrom=2026-11-09&dateTo=2026-11-15")


def test_raketa_registered() -> None:
    assert default_registry().get("raketa_ledokat_v1") is not None
