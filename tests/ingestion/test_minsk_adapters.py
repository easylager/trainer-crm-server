"""TASK-061: Minsk extract adapters publish canonical ice_sessions via scrape runs."""
from __future__ import annotations

import inspect
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from src.application.ice_session_use_cases import IceSessionPriceError, IceSessionValidationError
from src.ingestion.jobs import InMemoryParserJobStore, SqlAlchemyParserJobStore
from src.ingestion.normalize import IceSessionNormalizer
from src.ingestion.parsers import (
    ChizhovkaHtmlParser,
    DiamondHtmlParser,
    LedByHtmlParser,
    MinskArenaSaleframeParser,
    ParserRegistry,
    ZamokHtmlParser,
    default_registry,
)
from src.ingestion.publish import IceSessionPublisher, SqlAlchemyIceSessionPublisher
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import (
    IceScrapeRunRequired,
    InMemoryScrapeRunRecorder,
    SqlAlchemyScrapeRunRecorder,
    assert_can_replace_ice_sessions,
)
from src.ingestion.seed_config import MINSK_ARENA_SALEFRAME_CONFIG, PARSER_KEY_MINSK_ARENA
from src.ingestion.types import RUN_STATUS_EMPTY, RUN_STATUS_OK, CanonicalSlotDraft, ParserJob
from src.ingestion.validate import IceSessionValidator
from tests.ingestion.fakes import RecordingParser

ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 9, 5, 9, 0, tzinfo=timezone.utc)
_FIXTURES = ROOT / ".ai/data/fixtures"


def _job(*, arena_id: int, parser_key: str, config: dict, job_id: int = 1) -> ParserJob:
    return ParserJob(
        id=job_id,
        arena_id=arena_id,
        parser_key=parser_key,
        is_enabled=True,
        cadence="daily",
        next_run_at=_NOW - timedelta(minutes=5),
        last_run_at=None,
        config=config,
    )


def _minsk_arena_job(arena_id: int = 2, job_id: int = 1) -> ParserJob:
    cfg = dict(MINSK_ARENA_SALEFRAME_CONFIG)
    cfg["fixture_dir"] = str(_FIXTURES / "minsk-arena")
    return _job(arena_id=arena_id, parser_key=PARSER_KEY_MINSK_ARENA, config=cfg, job_id=job_id)


def _zamok_job(arena_id: int = 3, job_id: int = 2) -> ParserJob:
    return _job(
        arena_id=arena_id,
        parser_key="zamok_html_v1",
        job_id=job_id,
        config={
            "url": "https://tczamok.by/entertainments/ice-rink",
            "timezone": "Europe/Minsk",
            "horizon_days": 7,
            "slot_start_suffix": ":15",
            "kind": "public_skate",
            "duration_minutes": 45,
            "run_date": "2026-09-05",
            "prices_already_minor": True,
            "fixture_dir": str(_FIXTURES / "minsk-zamok"),
            "requires_by_egress": False,
        },
    )


def _chizhovka_job(arena_id: int = 6, job_id: int = 3) -> ParserJob:
    return _job(
        arena_id=arena_id,
        parser_key="chizhovka_html_v1",
        job_id=job_id,
        config={
            "schedule_url": "https://chizhovka-arena.by/fizkultura-i-sport/katanie-na-konkah",
            "prices_url": "https://chizhovka-arena.by/czeny/katanie-na-konkah",
            "timezone": "Europe/Minsk",
            "default_duration_minutes": 60,
            "kind": "public_skate",
            "keep_rink_labels": ["МА", "БА"],
            "run_year": 2026,
            "prices_already_minor": True,
            "fixture_dir": str(_FIXTURES / "minsk-chizhovka"),
            "requires_by_egress": False,
        },
    )


def _ledby_job(arena_id: int = 5, job_id: int = 4) -> ParserJob:
    return _job(
        arena_id=arena_id,
        parser_key="ledby_html_v1",
        job_id=job_id,
        config={
            "schedule_url": "http://led.by/category/timetable/",
            "prices_url": "http://led.by/mass_skating/",
            "timezone": "Europe/Minsk",
            "kind": "public_skate",
            "prices_already_minor": True,
            "fixture_dir": str(_FIXTURES / "minsk-ledby"),
            "requires_by_egress": False,
        },
    )


def _diamond_job(arena_id: int = 7, job_id: int = 5) -> ParserJob:
    return _job(
        arena_id=arena_id,
        parser_key="diamond_html_v1",
        job_id=job_id,
        config={
            "schedule_url": "https://diamondcity.by/ledovaya-arena",
            "timezone": "Europe/Minsk",
            "kind": "public_skate",
            "keep_labels": ["МК"],
            "drop_labels": [
                "ОХМ",
                "ШРС",
                "ТОРНАДО",
                "Тех.обслуживание",
                "ЗВЕЗДОЧКА",
                "МИР БЕЗ ГРАНИЦ",
                "КФК",
            ],
            "disco_marker": "ДИСКОТЕКА",
            "default_duration_minutes": 45,
            "run_year": 2026,
            "prices_already_minor": True,
            "fixture_dir": str(_FIXTURES / "minsk-diamond"),
            "requires_by_egress": False,
        },
    )


def _registry(*parsers) -> ParserRegistry:
    registry = ParserRegistry()
    for parser in parsers:
        registry.register(parser)
    return registry


@pytest.mark.asyncio
async def test_saleframe_fixture_yields_two_public_skate_slots() -> None:
    """AC-001: 17:00–17:45 and 19:00–19:45, adult 850, child 600, rental null; prices already minor."""
    expected = json.loads((_FIXTURES / "minsk-arena/expected.json").read_text(encoding="utf-8"))
    parser = MinskArenaSaleframeParser()
    job = _minsk_arena_job()
    extraction = await parser.extract(job)
    drafts = IceSessionNormalizer().normalize(extraction, job, now=_NOW)
    validated = IceSessionValidator().validate(drafts)

    assert len(validated) == 2
    by_start = {slot.starts_at_local: slot for slot in validated}
    first = by_start[time(17, 0)]
    second = by_start[time(19, 0)]
    for slot, gold in zip((first, second), expected["sessions"], strict=True):
        assert slot.kind == "public_skate"
        assert slot.local_date == date.fromisoformat(gold["local_date"])
        assert slot.starts_at_local.strftime("%H:%M") == gold["starts_at_local"]
        assert slot.ends_at_local.strftime("%H:%M") == gold["ends_at_local"]
        assert slot.price_adult_minor == 850
        assert slot.price_child_minor == 600
        assert slot.price_rental_minor is None
        assert slot.price_adult_minor == gold["price_adult_minor"]
    assert (first.ends_at_utc - first.starts_at_utc) == timedelta(minutes=45)


@pytest.mark.asyncio
async def test_zamok_and_chizhovka_html_adapters_match_expected() -> None:
    """AC-002: two Minsk HTML adapters on fixtures create MK slots."""
    zamok_now = datetime(2026, 9, 5, 6, 0, tzinfo=timezone.utc)
    chizhovka_now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    zamok_job = _zamok_job()
    chizhovka_job = _chizhovka_job()
    zamok_ext = await ZamokHtmlParser().extract(zamok_job)
    zamok_ok = IceSessionValidator().validate(
        IceSessionNormalizer().normalize(zamok_ext, zamok_job, now=zamok_now)
    )
    zamok_expected = json.loads((_FIXTURES / "minsk-zamok/expected.json").read_text(encoding="utf-8"))
    assert len(zamok_ok) == len(zamok_expected["sessions"])
    sample = next(
        slot for slot in zamok_ok if slot.local_date == date(2026, 9, 5) and slot.starts_at_local == time(10, 15)
    )
    assert sample.price_adult_minor == 1100
    assert sample.price_child_minor == 900
    assert sample.price_rental_minor == 900

    chiz_ext = await ChizhovkaHtmlParser().extract(chizhovka_job)
    chiz_ok = IceSessionValidator().validate(
        IceSessionNormalizer().normalize(chiz_ext, chizhovka_job, now=chizhovka_now)
    )
    chiz_expected = json.loads((_FIXTURES / "minsk-chizhovka/expected.json").read_text(encoding="utf-8"))
    assert len(chiz_ok) == len(chiz_expected["sessions"])
    gold = chiz_expected["sessions"][0]
    hit = next(
        slot
        for slot in chiz_ok
        if slot.local_date == date.fromisoformat(gold["local_date"])
        and slot.starts_at_local.strftime("%H:%M") == gold["starts_at_local"]
    )
    assert hit.price_adult_minor == 1000
    assert hit.price_child_minor == 700
    assert hit.price_rental_minor == 500
    assert hit.session_label == "МА"


@pytest.mark.asyncio
async def test_ledby_html_adapter_matches_expected_sample() -> None:
    job = _ledby_job()
    now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    extraction = await LedByHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    assert len(slots) >= 12
    assert {slot.kind for slot in slots} == {"public_skate"}
    disco = next(
        slot for slot in slots if slot.local_date == date(2026, 9, 5) and slot.starts_at_local == time(20, 15)
    )
    assert disco.session_label == "дискотека"
    assert disco.price_adult_minor == 1000
    assert disco.price_child_minor == 800
    assert disco.price_rental_minor == 500


@pytest.mark.asyncio
async def test_diamond_drops_oxm_school_and_ice_rental() -> None:
    """AC-003: ОХМ / school / ice rental never become ice_sessions kinds."""
    extraction = await DiamondHtmlParser().extract(_diamond_job())
    kind_raws = {slot.kind_raw.lower() for slot in extraction.slots}
    assert any("мк" in raw or "массов" in raw for raw in kind_raws)
    assert not any("охм" in raw for raw in kind_raws)
    assert not any("школ" in raw or "шрс" in raw for raw in kind_raws)
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    slots = IceSessionValidator().validate(
        IceSessionNormalizer().normalize(extraction, _diamond_job(), now=now)
    )
    assert slots
    assert all(slot.kind in {"public_skate", "open_ice"} for slot in slots)


@pytest.mark.asyncio
async def test_diamond_dual_interval_mk_cell_yields_two_slots() -> None:
    """One MK cell with two intervals (Thu 10 Sep) must become two public_skate slots."""
    job = _diamond_job()
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    extraction = await DiamondHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    thu = [
        slot
        for slot in slots
        if slot.local_date == date(2026, 9, 10)
        and slot.starts_at_local in {time(16, 45), time(17, 45)}
    ]
    by_start = {slot.starts_at_local: slot for slot in thu}
    assert set(by_start) == {time(16, 45), time(17, 45)}
    assert by_start[time(16, 45)].ends_at_local == time(17, 30)
    assert by_start[time(17, 45)].ends_at_local == time(18, 30)
    assert all(slot.kind == "public_skate" for slot in thu)
    assert all(slot.session_label is None for slot in thu)


@pytest.mark.asyncio
async def test_diamond_extracts_all_gold_mk_slots() -> None:
    """Gold 44 MK slots, including div-wrapped cells the span-only extractor skipped."""
    expected = json.loads((_FIXTURES / "minsk-diamond/expected.json").read_text(encoding="utf-8"))
    job = _diamond_job()
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    extraction = await DiamondHtmlParser().extract(job)
    slots = IceSessionValidator().validate(IceSessionNormalizer().normalize(extraction, job, now=now))
    gold_keys = {
        (row["local_date"], row["starts_at_local"], row.get("session_label"))
        for row in expected["sessions"]
    }
    got_keys = {
        (slot.local_date.isoformat(), slot.starts_at_local.strftime("%H:%M"), slot.session_label)
        for slot in slots
    }
    assert len(expected["sessions"]) == 44
    assert got_keys == gold_keys
    assert all(slot.kind == "public_skate" for slot in slots)


@pytest.mark.asyncio
async def test_empty_run_does_not_delete_future_slots(db_session) -> None:
    """AC-004: empty must not wipe future ice_sessions; rerun does not duplicate."""
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Лёд-061', 'ул. Тестовая, 1', true, true)
                    RETURNING id
                    """
                ),
                {"cid": int(city)},
            )
        ).scalar_one()
    )
    await db_session.flush()
    template = _minsk_arena_job(arena_id=arena_id, job_id=0)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_parser_jobs
                (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
            VALUES (:aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb))
            """
        ),
        {
            "aid": arena_id,
            "pkey": PARSER_KEY_MINSK_ARENA,
            "next_run": _NOW - timedelta(minutes=1),
            "cfg": json.dumps(template.config, ensure_ascii=False),
        },
    )
    await db_session.flush()
    job_id = int(
        (
            await db_session.execute(
                text("SELECT id FROM ice_parser_jobs WHERE arena_id = :aid"),
                {"aid": arena_id},
            )
        ).scalar_one()
    )

    store = SqlAlchemyParserJobStore(db_session)
    recorder = SqlAlchemyScrapeRunRecorder(db_session)
    publisher = SqlAlchemyIceSessionPublisher(db_session)
    sched = IceIngestScheduler(
        store=store,
        recorder=recorder,
        registry=_registry(MinskArenaSaleframeParser()),
        publisher=publisher,
    )

    first = await sched.run_due(_NOW)
    await db_session.flush()
    count_after_ok = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM ice_sessions WHERE arena_id = :aid"),
                {"aid": arena_id},
            )
        ).scalar_one()
    )
    assert first[0].status == RUN_STATUS_OK
    assert count_after_ok == 2

    second = await sched.run_due(_NOW + timedelta(days=1))
    await db_session.flush()
    count_after_rerun = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM ice_sessions WHERE arena_id = :aid"),
                {"aid": arena_id},
            )
        ).scalar_one()
    )
    assert second[0].status == RUN_STATUS_OK
    assert count_after_rerun == 2

    empty_parser = RecordingParser()
    await db_session.execute(
        text("UPDATE ice_parser_jobs SET parser_key = :pkey, next_run_at = :next_run WHERE id = :id"),
        {"pkey": empty_parser.parser_key, "next_run": _NOW, "id": job_id},
    )
    await db_session.flush()
    empty_runs = await IceIngestScheduler(
        store=store,
        recorder=recorder,
        registry=_registry(empty_parser),
        publisher=publisher,
    ).run_due(_NOW)
    await db_session.flush()
    assert empty_runs[0].status == RUN_STATUS_EMPTY
    still = int(
        (
            await db_session.execute(
                text("SELECT count(*) FROM ice_sessions WHERE arena_id = :aid AND starts_at_utc > :now"),
                {"aid": arena_id, "now": _NOW},
            )
        ).scalar_one()
    )
    assert still == 2


def test_publisher_requires_ok_scrape_run() -> None:
    """AC-005: no ice_sessions write without an ok scrape run id."""
    with pytest.raises(IceScrapeRunRequired):
        assert_can_replace_ice_sessions(None, run_id=None)
    sched_src = Path("src/ingestion/scheduler.py").read_text(encoding="utf-8")
    assert "publisher" in sched_src
    assert "INSERT INTO ice_sessions" not in sched_src
    for cls in (MinskArenaSaleframeParser, ZamokHtmlParser, ChizhovkaHtmlParser, LedByHtmlParser):
        source = inspect.getsource(cls)
        assert "INSERT" not in source
        assert "ice_sessions" not in source


@pytest.mark.asyncio
async def test_saleframe_and_html_share_ice_session_columns(db_session) -> None:
    """AC-006: published rows share ice_sessions columns; invalid drafts never persist."""
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")

    async def _arena(name: str) -> int:
        return int(
            (
                await db_session.execute(
                    text(
                        """
                        INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                        VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                        RETURNING id
                        """
                    ),
                    {"cid": int(city), "name": name},
                )
            ).scalar_one()
        )

    saleframe_arena = await _arena("Лёд-061-arena")
    zamok_arena = await _arena("Лёд-061-zamok")
    await db_session.flush()

    jobs = [
        _minsk_arena_job(arena_id=saleframe_arena, job_id=11),
        _zamok_job(arena_id=zamok_arena, job_id=12),
    ]
    for job in jobs:
        await db_session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs
                    (id, arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES
                    (:id, :aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb))
                """
            ),
            {
                "id": job.id,
                "aid": job.arena_id,
                "pkey": job.parser_key,
                "next_run": _NOW - timedelta(minutes=1),
                "cfg": json.dumps(job.config, ensure_ascii=False),
            },
        )
    await db_session.flush()

    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=SqlAlchemyScrapeRunRecorder(db_session),
        registry=_registry(MinskArenaSaleframeParser(), ZamokHtmlParser()),
        publisher=SqlAlchemyIceSessionPublisher(db_session),
    )
    await sched.run_due(_NOW)
    await db_session.flush()

    columns = (
        await db_session.execute(
            text(
                """
                SELECT arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                       starts_at_local, ends_at_local, price_adult_minor, price_child_minor,
                       price_rental_minor, currency_code, status, observed_at, valid_until,
                       session_label, age_note, source_id
                FROM ice_sessions
                WHERE arena_id IN (:a, :b)
                ORDER BY arena_id, starts_at_utc
                """
            ),
            {"a": saleframe_arena, "b": zamok_arena},
        )
    ).mappings().all()
    assert columns
    saleframe_rows = [row for row in columns if row["arena_id"] == saleframe_arena]
    zamok_rows = [row for row in columns if row["arena_id"] == zamok_arena]
    assert saleframe_rows
    assert zamok_rows
    assert set(saleframe_rows[0].keys()) == set(zamok_rows[0].keys())
    assert {row["kind"] for row in columns} <= {"public_skate", "open_ice"}
    assert all(row["currency_code"] == "BYN" for row in columns)

    bad = CanonicalSlotDraft(
        arena_id=saleframe_arena,
        kind="public_skate",
        starts_at_utc=_NOW,
        ends_at_utc=_NOW + timedelta(minutes=45),
        local_date=date(2026, 9, 6),
        starts_at_local=time(17, 0),
        ends_at_local=time(17, 45),
        price_adult_minor=-1,
        price_child_minor=600,
        price_rental_minor=None,
        currency_code="BYN",
        status="active",
        observed_at=_NOW,
        valid_until=_NOW + timedelta(hours=2),
    )
    with pytest.raises((IceSessionValidationError, IceSessionPriceError)):
        IceSessionValidator().validate([bad])

    assert default_registry().get(PARSER_KEY_MINSK_ARENA) is not None
    assert default_registry().get("zamok_html_v1") is not None
    assert default_registry().get("chizhovka_html_v1") is not None


def test_minsk_arena_live_urls_hit_abws_not_saleframe_html() -> None:
    """Live extract must call ABWS JSON, not the Vue saleframe shell."""
    from zoneinfo import ZoneInfo

    from src.ingestion.adapters import (
        minsk_arena_calendar_url,
        minsk_arena_events_url,
        minsk_arena_init_url,
    )

    cfg = MINSK_ARENA_SALEFRAME_CONFIG
    init = minsk_arena_init_url(cfg)
    calendar = minsk_arena_calendar_url(cfg)
    events = minsk_arena_events_url(
        cfg, local_date=date(2026, 9, 6), tz=ZoneInfo("Europe/Minsk")
    )
    assert init.startswith("https://abws.minskarena.by/api/v3/frame/init")
    assert "seid=55" in init
    assert calendar == "https://abws.minskarena.by/api/v1/frame/service/55/calendar"
    assert "expand=prices" in events
    assert "from=" in events and "to=" in events
    assert "saleframe.minskarena.by" not in init
    assert "saleframe.minskarena.by" not in calendar
    assert "saleframe.minskarena.by" not in events
