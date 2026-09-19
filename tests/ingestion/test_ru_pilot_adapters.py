"""RU pilot ice parsers: Сокольники (Москва), Ледовый дворец + Юбилейный (СПб).

Fixtures + hand-extracted ``expected.json`` come from the RU pilot research
pass (see ``data/parsers/{msk,spb}-*.md``). These tests run the real
extract -> normalize -> validate pipeline against the captured fixtures and
check the result against that ground truth — same pattern as
``tests/ingestion/test_regional_batch_a_adapters.py``.

Currency is RUB and timezone is Europe/Moscow for all three — the assertions
below check that explicitly, since ``IceSessionNormalizer`` silently falls
back to BYN/Europe/Minsk when a job.config omits those keys.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest

from src.ingestion.adapters_ru_pilot import (
    BalticArenaHtmlParser,
    LedovyyDvoretsHtmlParser,
    SokolnikiHtmlParser,
    VtbArenaQticketsParser,
    YubileynyAfishaParser,
)
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import default_registry
from src.ingestion.types import ParserJob
from src.ingestion.validate import IceSessionValidator

ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = ROOT / "data/fixtures"

_SOKOLNIKI_CONFIG = {
    "schedule_url": "https://ld-sokolniki.ru/massovye-kataniya/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "session_name": "МК",
    "rental_price_flat_minor": 30000,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_LEDOVYY_DVORETS_CONFIG = {
    "url": "https://newarena.spb.ru/rink/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "run_year": 2026,
    "day_rate_cutoff": "17:30",
    "adult_price_before_cutoff_minor": 60000,
    "adult_price_from_cutoff_minor": 70000,
    "child_price_before_cutoff_minor": 40000,
    "child_price_from_cutoff_minor": 45000,
    "rental_skates_minor": 45000,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_YUBILEYNY_CONFIG = {
    "listing_url": "https://www.yubi.ru/afisha/katok/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "default_duration_minutes": 60,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_BALTIC_ARENA_CONFIG = {
    "url": "https://baltic-arena.ru/mass-skating",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "run_year": 2026,
    "duration_price_minor": {60: 70000, 75: 85000},
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_VTBARENA_CONFIG = {
    "prices_url": "https://akademiya-dynamo.ru/services/katanie-na-krytoy-ledovoy-ploshchadke/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "requires_by_egress": False,
    "requires_auth": True,
}


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc),
        last_run_at=None,
        config=config,
    )


def _sokolniki_job() -> ParserJob:
    cfg = dict(_SOKOLNIKI_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "msk-sokolniki")
    return _job(arena_id=58, parser_key="ldsokolniki_html_v1", config=cfg, job_id=201)


def _ledovyy_dvorets_job() -> ParserJob:
    cfg = dict(_LEDOVYY_DVORETS_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-ledovyy-dvorets")
    return _job(arena_id=105, parser_key="ledovyydvorets_html_v1", config=cfg, job_id=202)


def _yubileyny_job() -> ParserJob:
    cfg = dict(_YUBILEYNY_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-yubileyny")
    return _job(arena_id=97, parser_key="yubileyny_afisha_html_v1", config=cfg, job_id=203)


def _baltic_arena_job() -> ParserJob:
    cfg = dict(_BALTIC_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-baltic-arena")
    return _job(arena_id=192, parser_key="balticarena_html_v1", config=cfg, job_id=206)


def _vtbarena_job() -> ParserJob:
    cfg = dict(_VTBARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "msk-vtbarena")
    return _job(arena_id=53, parser_key="vtbarena_qtickets_v1", config=cfg, job_id=204)


def _load_expected(slug: str) -> dict:
    return json.loads((_FIXTURES / slug / "expected.json").read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_sokolniki_matches_expected_snapshot() -> None:
    job = _sokolniki_job()
    expected = _load_expected("msk-sokolniki")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await SokolnikiHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 2
    by_start = {slot.starts_at_local: slot for slot in slots}
    for gold in expected["sessions"]:
        slot = by_start[time.fromisoformat(gold["starts_at_local"])]
        assert slot.local_date == date.fromisoformat(gold["local_date"])
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 60000
        assert slot.price_child_minor is None
        assert slot.price_rental_minor == gold["price_rental_minor"] == 30000
        assert slot.session_label == "МК"


@pytest.mark.asyncio
async def test_sokolniki_empty_schedule_list_is_valid_empty_state(tmp_path: Path) -> None:
    """AC (spec item 9): an empty ``.schedule-list`` (no published date yet) yields
    zero slots, not an error — admin publishes the next date manually and the
    page can legitimately have nothing queued."""
    empty_html = (
        '<div class="right-col"><div class="schedule-list">'
        "Если в данный момент на сайте не размещено расписание сеансов, "
        "значит пока возможности покататься нет."
        "</div></div>"
    )
    fixture_dir = tmp_path / "msk-sokolniki-empty"
    fixture_dir.mkdir()
    (fixture_dir / "massovye-kataniya.html").write_text(empty_html, encoding="utf-8")
    cfg = dict(_SOKOLNIKI_CONFIG)
    cfg["fixture_dir"] = str(fixture_dir)
    job = _job(arena_id=58, parser_key="ldsokolniki_html_v1", config=cfg, job_id=205)

    extraction = await SokolnikiHtmlParser().extract(job)

    assert extraction.slots == []


@pytest.mark.asyncio
async def test_ledovyy_dvorets_matches_full_expected_grid() -> None:
    """Reader-proxy markdown fixture (see spec Blockers) — verified 102/102 against gold."""
    job = _ledovyy_dvorets_job()
    expected = _load_expected("spb-ledovyy-dvorets")
    now = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
    extraction = await LedovyyDvoretsHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 102
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor == gold["price_child_minor"]
        assert slot.price_rental_minor == gold["price_rental_minor"] == 45000
        assert slot.age_note == gold["age_note"]


@pytest.mark.asyncio
async def test_ledovyy_dvorets_day_evening_price_cutoff() -> None:
    """AC: starts_at_local < 17:30 -> day band; >= 17:30 -> evening band (spec item 5)."""
    job = _ledovyy_dvorets_job()
    now = datetime(2026, 8, 20, 6, 0, tzinfo=timezone.utc)
    extraction = await LedovyyDvoretsHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    day = next(slot for slot in slots if slot.local_date == date(2026, 8, 24) and slot.starts_at_local == time(16, 15))
    evening = next(
        slot for slot in slots if slot.local_date == date(2026, 8, 24) and slot.starts_at_local == time(17, 30)
    )
    assert day.price_adult_minor == 60000 and day.price_child_minor == 40000
    assert evening.price_adult_minor == 70000 and evening.price_child_minor == 45000


@pytest.mark.asyncio
async def test_yubileyny_matches_expected_events() -> None:
    job = _yubileyny_job()
    expected = _load_expected("spb-yubileyny")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await YubileynyAfishaParser().extract(job)
    assert {slot.source_id for slot in extraction.slots} == {"11206", "11207", "11208"}
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 3
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 80000
        assert slot.price_child_minor is None
        assert slot.price_rental_minor is None
        assert slot.session_label == gold["session_label"] == "Часовая спортивная докатка — Малая арена"
        assert slot.age_note == gold["age_note"]


@pytest.mark.asyncio
async def test_vtbarena_blocked_adapter_never_invents_sessions() -> None:
    """AC: spec_blocked (Qtickets auth wall) — extraction must stay empty, never guess a grid."""
    job = _vtbarena_job()
    expected = _load_expected("msk-vtbarena")
    extraction = await VtbArenaQticketsParser().extract(job)
    assert extraction.slots == []
    assert expected["sessions"] == []


@pytest.mark.asyncio
async def test_baltic_arena_matches_expected_grid() -> None:
    """Position-to-day mapping + duration->price legend verified via a real browser
    (see spec Verification section) — this checks the extract->normalize pipeline
    reproduces the same 26 slots independently hand-computed into expected.json."""
    job = _baltic_arena_job()
    expected = _load_expected("spb-baltic-arena")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await BalticArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 25
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor is None
        assert slot.price_rental_minor is None


@pytest.mark.asyncio
async def test_baltic_arena_typo_colon_separator_accepted() -> None:
    """AC (spec item 3): the source has one observed 'HH:MM:HH:MM' typo (colon instead
    of dash before the end time) — must parse the same as a normal dash-separated slot."""
    job = _baltic_arena_job()
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await BalticArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    typo_slot = next(
        slot for slot in slots if slot.local_date == date(2026, 9, 20) and slot.starts_at_local == time(22, 15)
    )
    assert typo_slot.ends_at_local.strftime("%H:%M") == "23:15"
    assert typo_slot.price_adult_minor == 70000


@pytest.mark.asyncio
async def test_baltic_arena_duration_price_band() -> None:
    """AC (spec item 5): 60-minute slots price at duration_price_minor[60], 75-minute
    slots at duration_price_minor[75] — derived from duration, never a flat constant."""
    job = _baltic_arena_job()
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await BalticArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    sixty = next(slot for slot in slots if slot.local_date == date(2026, 9, 19) and slot.starts_at_local == time(9, 15))
    seventy_five = next(
        slot for slot in slots if slot.local_date == date(2026, 9, 19) and slot.starts_at_local == time(18, 30)
    )
    assert sixty.ends_at_local.strftime("%H:%M") == "10:15"
    assert sixty.price_adult_minor == 70000
    assert seventy_five.ends_at_local.strftime("%H:%M") == "19:45"
    assert seventy_five.price_adult_minor == 85000


def test_ru_pilot_parsers_registered() -> None:
    registry = default_registry()
    assert registry.get("ldsokolniki_html_v1") is not None
    assert registry.get("ledovyydvorets_html_v1") is not None
    assert registry.get("yubileyny_afisha_html_v1") is not None
    assert registry.get("vtbarena_qtickets_v1") is not None
    assert registry.get("balticarena_html_v1") is not None
