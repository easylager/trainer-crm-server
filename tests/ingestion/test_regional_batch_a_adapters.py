"""Batch-A regional BY ice parsers: Брест, Барановичи, Кобрин, Пинск.

Fixtures + hand-extracted ``expected.json`` come from a prior SPEC research
pass (see ``.ai/parsers/<slug>.md``). These tests run the real extract →
normalize → validate pipeline against the captured fixtures and check the
result against that ground truth — same pattern as
``tests/ingestion/test_minsk_adapters.py``.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_regional_batch_a import (
    BaranovichiLdsParser,
    BrestLdsParser,
    KobrinLdsParser,
    PinskVolnaParser,
)
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.seed_config_regional_batch_a import (
    BARANOVICHI_LDS_CONFIG,
    BREST_LDS_CONFIG,
    KOBRIN_LDS_CONFIG,
    PARSER_KEY_BARANOVICHI_LDS,
    PARSER_KEY_BREST_LDS,
    PARSER_KEY_KOBRIN_LDS,
    PARSER_KEY_PINSK_VOLNA,
    PINSK_VOLNA_CONFIG,
)
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"
_NOW = datetime(2026, 8, 25, 9, 0, tzinfo=timezone.utc)


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="weekly",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config=config,
    )


def _brest_job() -> ParserJob:
    cfg = dict(BREST_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "brest-lds")
    cfg["run_date"] = "2026-08-31"
    # Неделя фото 31.08 — сеанс 60 минут; с октября 45 (см. test_brest_lds_session_is_45_minutes_now).
    cfg["fixed_end"] = "22:15"
    return _job(arena_id=22, parser_key=PARSER_KEY_BREST_LDS, config=cfg, job_id=101)


def _baranovichi_job() -> ParserJob:
    cfg = dict(BARANOVICHI_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "baranovichi-lds")
    return _job(arena_id=23, parser_key=PARSER_KEY_BARANOVICHI_LDS, config=cfg, job_id=102)


def _kobrin_job() -> ParserJob:
    cfg = dict(KOBRIN_LDS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "kobrin-lds")
    return _job(arena_id=25, parser_key=PARSER_KEY_KOBRIN_LDS, config=cfg, job_id=103)


def _pinsk_job() -> ParserJob:
    cfg = dict(PINSK_VOLNA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "pinsk-volna")
    return _job(arena_id=24, parser_key=PARSER_KEY_PINSK_VOLNA, config=cfg, job_id=104)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_brest_lds_matches_expected_photo_week() -> None:
    job = _brest_job()
    expected = _load_expected("brest-lds")
    extraction = await BrestLdsParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))

    assert len(slots) == len(expected["sessions"]) == 7
    by_date = {slot.local_date: slot for slot in slots}
    for gold in expected["sessions"]:
        slot = by_date[date.fromisoformat(gold["local_date"])]
        assert slot.kind == "open_ice"
        assert slot.starts_at_local.strftime("%H:%M") == gold["starts_at_local"] == "21:15"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"] == "22:15"
        assert slot.price_adult_minor == gold["price_adult_minor"] == 630
        assert slot.price_child_minor == gold["price_child_minor"] == 530
        assert slot.price_rental_minor is None
        assert slot.session_label is None, "«СВ кат» — сокращение с фото, клиенту его не показываем"


@pytest.mark.asyncio
async def test_baranovichi_lds_matches_expected_week() -> None:
    job = _baranovichi_job()
    expected = _load_expected("baranovichi-lds")
    extraction = await BaranovichiLdsParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))

    assert len(slots) == len(expected["sessions"]) == 16
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 480
        assert slot.price_child_minor == gold["price_child_minor"] == 360
        assert slot.price_rental_minor == gold["price_rental_minor"] == 500


@pytest.mark.asyncio
async def test_kobrin_lds_matches_expected_week() -> None:
    job = _kobrin_job()
    expected = _load_expected("kobrin-lds")
    extraction = await KobrinLdsParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))

    assert len(slots) == len(expected["sessions"]) == 18
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 330
        assert slot.price_child_minor == gold["price_child_minor"] == 250
        assert slot.price_rental_minor == gold["price_rental_minor"] == 430


@pytest.mark.asyncio
async def test_pinsk_volna_matches_expected_horizon() -> None:
    job = _pinsk_job()
    expected = _load_expected("pinsk-volna")
    extraction = await PinskVolnaParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=_NOW))

    assert len(slots) == len(expected["sessions"]) == 18
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 440
        assert slot.price_child_minor == gold["price_child_minor"] == 418
        assert slot.price_rental_minor == gold["price_rental_minor"] == 420


@pytest.mark.asyncio
async def test_pinsk_volna_reads_weekday_glued_to_the_date(tmp_path: Path) -> None:
    """Неделя 19–25 окт 2026: часть дней на сайте без пробела перед датой."""
    schedule = """
    <p>Расписание массового катания</p>
    <p>Понедельник19.10.2026</p>
    <p>09.45 – 10.30</p>
    <p>Четверг22.10.2026</p>
    <p>10.00 – 10.45</p>
    <p>21.00 – 21.45</p>
    <p>Среда 21.10.2026</p>
    <p>11.00 – 11.45</p>
    <p>В расписании возможны изменения</p>
    """
    (tmp_path / "schedule.html").write_text(schedule, encoding="utf-8")
    shutil.copy(_FIXTURES / "pinsk-volna" / "tariff.html", tmp_path / "tariff.html")
    cfg = dict(PINSK_VOLNA_CONFIG)
    cfg["fixture_dir"] = str(tmp_path)
    job = _job(arena_id=24, parser_key=PARSER_KEY_PINSK_VOLNA, config=cfg, job_id=105)
    extraction = await PinskVolnaParser().extract(job)
    keys = {(slot.local_date, slot.starts_at_local) for slot in extraction.slots}
    assert ("2026-10-19", "09:45") in keys
    assert ("2026-10-22", "10:00") in keys
    assert ("2026-10-22", "21:00") in keys
    assert ("2026-10-21", "11:00") in keys


def test_brest_lds_session_is_45_minutes_now() -> None:
    """С октября 2026 «СВ кат» в Бресте — 21:15–22:00, а не час, как на фото 31.08."""
    assert BREST_LDS_CONFIG["fixed_start"] == "21:15"
    assert BREST_LDS_CONFIG["fixed_end"] == "22:00"
    assert BREST_LDS_CONFIG["default_duration_minutes"] == 45
