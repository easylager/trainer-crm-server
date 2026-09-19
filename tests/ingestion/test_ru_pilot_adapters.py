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
    BugryArenaHtmlParser,
    GrandCanyonIceJsonParser,
    IceburgArenaJsonParser,
    LedovyyDvoretsHtmlParser,
    MagnitArenaHtmlParser,
    OzerkiCalendarParser,
    ParnasArenaTextParser,
    ShansArenaHtmlParser,
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

_ICEBURG_ARENA_CONFIG = {
    "url": "https://api.yclients.ru/api/v1/activity/1662558/search?from=2026-09-14&weekly_schedule=1&page=1&count=50",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_GRAND_CANYON_ICE_CONFIG = {
    "url": "https://cp.grand-ice.ru/api/schedules",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_OZERKI_CONFIG = {
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "google_api_key": "AIzaSyB6QYcTzKpA8kiRcjl47XJ_tEYbY2mcUVg",
    "horizon_days": 7,
    "rinks": [
        {
            "code": "big",
            "label": "Большая арена",
            "calendar_id": "jgl24dlkvmobfa4eh6ob5qomks@group.calendar.google.com",
            "fixture_file": "big-arena-events.json",
            "price_adult_minor": 50000,
        },
        {
            "code": "little",
            "label": "Малая арена",
            "calendar_id": "pj4va06gncb1vgv76864hbsh08@group.calendar.google.com",
            "fixture_file": "little-arena-events.json",
            "price_adult_minor": 40000,
        },
    ],
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_MAGNIT_ARENA_CONFIG = {
    "url": "http://magnit-arena.ru/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "run_year": 2026,
    "base_price_adult_minor": 60000,
    "rental_price_flat_minor": 30000,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_SHANS_ARENA_CONFIG = {
    "url": "https://shans-arena.ru/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "price_adult_minor": 90000,
    "price_child_minor": 90000,
    "price_rental_minor": 60000,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_PARNAS_ARENA_CONFIG = {
    "url": "https://parnas-arena.ru/massovie-kataniya",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "run_year": 2026,
    "base_price_adult_minor": 70000,
    "rental_price_flat_minor": 50000,
    "prices_already_minor": True,
    "requires_by_egress": False,
}

_BUGRY_ARENA_CONFIG = {
    "url": "https://spb-katok.ru/",
    "timezone": "Europe/Moscow",
    "currency_code": "RUB",
    "kind": "public_skate",
    "run_year": 2026,
    "default_duration_minutes": 45,
    "rinks": {
        "big": {"label": "Большая арена", "price_adult_minor": 60000, "price_rental_minor": 50000},
        "small": {"label": "Малая арена", "price_adult_minor": 60000, "price_rental_minor": 40000},
    },
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


def _iceburg_arena_job() -> ParserJob:
    cfg = dict(_ICEBURG_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-iceburg-arena")
    return _job(arena_id=193, parser_key="iceburgarena_yclients_v1", config=cfg, job_id=207)


def _grand_canyon_ice_job() -> ParserJob:
    cfg = dict(_GRAND_CANYON_ICE_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-grand-canyon-ice")
    return _job(arena_id=99, parser_key="grandice_json_v1", config=cfg, job_id=208)


def _ozerki_job() -> ParserJob:
    cfg = dict(_OZERKI_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-ozerki")
    return _job(arena_id=101, parser_key="ozerki_gcal_v1", config=cfg, job_id=209)


def _magnit_arena_job() -> ParserJob:
    cfg = dict(_MAGNIT_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-magnit-arena")
    return _job(arena_id=187, parser_key="magnitarena_html_v1", config=cfg, job_id=210)


def _shans_arena_job() -> ParserJob:
    cfg = dict(_SHANS_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-shans-arena")
    return _job(arena_id=100, parser_key="shansarena_html_v1", config=cfg, job_id=211)


def _parnas_arena_job() -> ParserJob:
    cfg = dict(_PARNAS_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-parnas-arena")
    return _job(arena_id=174, parser_key="parnasarena_text_v1", config=cfg, job_id=212)


def _bugry_arena_job() -> ParserJob:
    cfg = dict(_BUGRY_ARENA_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "spb-bugry-arena")
    return _job(arena_id=111, parser_key="bugryarena_html_v1", config=cfg, job_id=213)


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


@pytest.mark.asyncio
async def test_iceburg_arena_filters_to_mass_skating_only() -> None:
    """AC (spec item 3): the raw feed mixes in private bookings (figure-skating hours,
    hockey hours, group fitness) — only service.title == 'Массовое катание' may become
    a public ice_sessions row."""
    job = _iceburg_arena_job()
    expected = _load_expected("spb-iceburg-arena")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await IceburgArenaJsonParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 7
    by_source = {slot.source_id: slot for slot in slots}
    for gold in expected["sessions"]:
        slot = by_source[gold["source_id"]]
        assert slot.local_date == date.fromisoformat(gold["local_date"])
        assert slot.starts_at_local == time.fromisoformat(gold["starts_at_local"])
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.price_adult_minor == gold["price_adult_minor"] == 90000
        assert slot.price_child_minor is None
        assert slot.price_rental_minor is None


@pytest.mark.asyncio
async def test_iceburg_arena_price_converted_from_whole_units() -> None:
    """AC (spec item 4): the API's price_min/price_max are whole rubles (900), not minor
    units — must be multiplied by 100, unlike the HTML adapters' pre-minor job.config."""
    job = _iceburg_arena_job()
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await IceburgArenaJsonParser().extract(job)
    assert extraction.slots
    for slot in extraction.slots:
        assert slot.price_adult == 90000


@pytest.mark.asyncio
async def test_grand_canyon_ice_filters_to_free_skate_only() -> None:
    """AC (spec item 2): the raw feed mixes in 'Секция'/'Мероприятие' entries with no
    price and an explicit 'no free skate' note — only schedule_type.name == 'Свободное
    катание' may become a public ice_sessions row."""
    job = _grand_canyon_ice_job()
    expected = _load_expected("spb-grand-canyon-ice")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await GrandCanyonIceJsonParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 39
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
async def test_grand_canyon_ice_price_shared_across_date(tmp_path: Path) -> None:
    """AC (spec item 3): price is a single flat figure per date, applied to every
    schedule_time row for that date — not scraped per slot."""
    job = _grand_canyon_ice_job()
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await GrandCanyonIceJsonParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    same_day = [slot for slot in slots if slot.local_date == date(2026, 9, 20)]
    assert len(same_day) == 9
    assert {slot.price_adult_minor for slot in same_day} == {75000}


@pytest.mark.asyncio
async def test_ozerki_filters_to_free_skate_only_across_both_rinks() -> None:
    """AC (spec item 3): each calendar mixes in unlabeled busy-marker events (rental
    bookings) and, on the Малая арена calendar, 'Час хоккея' events — only
    summary.strip() == 'Свободное катание' may become a public ice_sessions row."""
    job = _ozerki_job()
    expected = _load_expected("spb-ozerki")
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await OzerkiCalendarParser().extract(job)
    assert extraction.slots
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 27
    by_source = {slot.source_id: slot for slot in slots}
    for gold in expected["sessions"]:
        slot = by_source[gold["source_id"]]
        assert slot.local_date == date.fromisoformat(gold["local_date"])
        assert slot.starts_at_local == time.fromisoformat(gold["starts_at_local"])
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor is None
        assert slot.price_rental_minor is None
        assert slot.session_label == gold["session_label"]


@pytest.mark.asyncio
async def test_ozerki_rink_price_differs_by_calendar() -> None:
    """AC (spec item 4): price is a flat per-rink constant from job.config, not read
    from the calendar — Большая арена (500 р) and Малая арена (400 р) differ."""
    job = _ozerki_job()
    now = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
    extraction = await OzerkiCalendarParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    by_label: dict[str, set[int]] = {}
    for slot in slots:
        by_label.setdefault(slot.session_label, set()).add(slot.price_adult_minor)
    assert by_label["Большая арена"] == {50000}
    assert by_label["Малая арена"] == {40000}


@pytest.mark.asyncio
async def test_magnit_arena_excludes_hockey_hour_rink() -> None:
    """AC (spec item 2): 'Ледовая Арена 2' is 'Час хоккея' (a different product) —
    only 'Ледовая Арена 1' ('массовое катание') may become a public ice_sessions row."""
    job = _magnit_arena_job()
    expected = _load_expected("spb-magnit-arena")
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await MagnitArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 62
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_child_minor is None
        assert slot.price_rental_minor == gold["price_rental_minor"] == 30000


@pytest.mark.asyncio
async def test_magnit_arena_promo_slot_overrides_base_price() -> None:
    """AC (spec item 4): a slot individually marked '/ NNN р.*' inline overrides the
    flat base_price_adult_minor for that one slot only."""
    job = _magnit_arena_job()
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await MagnitArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    promo = next(slot for slot in slots if slot.local_date == date(2026, 9, 14) and slot.starts_at_local == time(9, 45))
    base = next(slot for slot in slots if slot.local_date == date(2026, 9, 14) and slot.starts_at_local == time(6, 45))
    assert promo.price_adult_minor == 15000
    assert base.price_adult_minor == 60000


@pytest.mark.asyncio
async def test_shans_arena_filters_to_mass_class_only() -> None:
    """AC (spec item 2): the raw feed mixes 'schitem hockey'/'schitem figure' blocks
    into the same day chunk as 'schitem mass' — only the mass CSS class may become
    a public ice_sessions row."""
    job = _shans_arena_job()
    expected = _load_expected("spb-shans-arena")
    now = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    extraction = await ShansArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 23
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 90000
        assert slot.price_child_minor == gold["price_child_minor"] == 90000
        assert slot.price_rental_minor == gold["price_rental_minor"] == 60000


@pytest.mark.asyncio
async def test_shans_arena_handles_both_dash_and_no_dash_time_format() -> None:
    """AC (spec item 3): week 1's time cells print a literal dash between the two
    <p> tags; week 2 omits it entirely — both must parse to the same slot shape."""
    job = _shans_arena_job()
    now = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
    extraction = await ShansArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    with_dash = next(slot for slot in slots if slot.local_date == date(2026, 9, 19) and slot.starts_at_local == time(13, 45))
    without_dash = next(slot for slot in slots if slot.local_date == date(2026, 9, 21) and slot.starts_at_local == time(9, 15))
    assert with_dash.ends_at_local.strftime("%H:%M") == "14:45"
    assert without_dash.ends_at_local.strftime("%H:%M") == "10:15"


@pytest.mark.asyncio
async def test_parnas_arena_disco_slot_overrides_flat_price() -> None:
    """AC (spec item 4): the Saturday 'ice disco' slot is individually inline-priced
    (900 р) and overrides the flat base_price_adult_minor (700 р) for that slot only
    — and that inline figure is trusted over the page's separate, disagreeing
    'ЛЕДОВАЯ ДИСКОТЕКА: 800 р' price-list entry."""
    job = _parnas_arena_job()
    expected = _load_expected("spb-parnas-arena")
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await ParnasArenaTextParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 10
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"]
        assert slot.price_rental_minor == gold["price_rental_minor"] == 50000
    disco = by_key[(date(2026, 9, 19), time(20, 30))]
    assert disco.price_adult_minor == 90000


@pytest.mark.asyncio
async def test_parnas_arena_dot_separator_time_accepted() -> None:
    """AC (spec item 3): the Saturday slot's start time uses a dot separator
    ('20.30') instead of the colon every other slot uses ('HH:MM')."""
    job = _parnas_arena_job()
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await ParnasArenaTextParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    dot_slot = next(slot for slot in slots if slot.local_date == date(2026, 9, 19))
    assert dot_slot.starts_at_local == time(20, 30)


@pytest.mark.asyncio
async def test_bugry_arena_both_rinks_parsed_structurally() -> None:
    """AC (spec item 2): both Большая/Малая columns are parsed the same way — Малая
    happens to be empty in this snapshot, but the parser doesn't hardcode 'big only'."""
    job = _bugry_arena_job()
    expected = _load_expected("spb-bugry-arena")
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await BugryArenaHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))

    assert len(slots) == len(expected["sessions"]) == 47
    by_key = {(slot.local_date, slot.starts_at_local): slot for slot in slots}
    for gold in expected["sessions"]:
        key = (date.fromisoformat(gold["local_date"]), time.fromisoformat(gold["starts_at_local"]))
        slot = by_key[key]
        assert slot.kind == "public_skate"
        assert slot.currency_code == "RUB"
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == gold["price_adult_minor"] == 60000
        assert slot.price_rental_minor == gold["price_rental_minor"] == 50000
        assert slot.session_label == gold["session_label"] == "Большая арена"


@pytest.mark.asyncio
async def test_bugry_arena_default_duration_applied_no_printed_end_time() -> None:
    """AC (spec item 2): the source prints only start times ('HH-MM', dash not colon)
    — end time comes entirely from job.config default_duration_minutes."""
    job = _bugry_arena_job()
    now = datetime(2026, 9, 13, 6, 0, tzinfo=timezone.utc)
    extraction = await BugryArenaHtmlParser().extract(job)
    assert all(slot.ends_at_local is None for slot in extraction.slots)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    slot = next(slot for slot in slots if slot.local_date == date(2026, 9, 14) and slot.starts_at_local == time(9, 0))
    assert slot.ends_at_local.strftime("%H:%M") == "09:45"


def test_ru_pilot_parsers_registered() -> None:
    registry = default_registry()
    assert registry.get("ldsokolniki_html_v1") is not None
    assert registry.get("ledovyydvorets_html_v1") is not None
    assert registry.get("yubileyny_afisha_html_v1") is not None
    assert registry.get("vtbarena_qtickets_v1") is not None
    assert registry.get("balticarena_html_v1") is not None
    assert registry.get("iceburgarena_yclients_v1") is not None
    assert registry.get("grandice_json_v1") is not None
    assert registry.get("ozerki_gcal_v1") is not None
    assert registry.get("magnitarena_html_v1") is not None
    assert registry.get("shansarena_html_v1") is not None
    assert registry.get("parnasarena_text_v1") is not None
    assert registry.get("bugryarena_html_v1") is not None
