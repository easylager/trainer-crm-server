"""TASK-187: окно публикации — от «сейчас» до горизонта job, а не [min, max] дат выдачи.

DB-тесты используют ``seed_city_id`` (tests/ingestion/conftest.py) и не пропускаются
на пустой CI-базе.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.ingestion.jobs import SqlAlchemyParserJobStore
from src.ingestion.parsers import ParserRegistry
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.publish_horizon import (
    DEFAULT_HORIZON_DAYS,
    publish_horizon_days,
    publish_local_date_window,
)
from src.ingestion.scheduler import IceIngestScheduler
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord
from tests.ingestion.fakes import FakeJsonWidgetParser

_MINSK = ZoneInfo("Europe/Minsk")
# 12:00 по Минску 15 марта: утро «сегодня» уже прошло, вечер ещё впереди.
_FINISHED = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)
_TODAY = _FINISHED.astimezone(_MINSK).date()


def _at(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, tzinfo=_MINSK).astimezone(timezone.utc)


def _draft(arena_id: int, day: date, start: time, *, minutes: int = 60) -> CanonicalSlotDraft:
    starts = _at(day, start)
    ends = starts + timedelta(minutes=minutes)
    return CanonicalSlotDraft(
        arena_id=arena_id,
        kind="public_skate",
        starts_at_utc=starts,
        ends_at_utc=ends,
        local_date=day,
        starts_at_local=start,
        ends_at_local=ends.astimezone(_MINSK).time().replace(tzinfo=None),
        price_adult_minor=1000,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status="active",
        observed_at=_FINISHED,
        valid_until=ends,
        source_id=f"test:{day.isoformat()}:{start.isoformat()}",
    )


async def _arena(db_session, city_id: int, name: str = "Лёд-187") -> int:
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
                {"cid": city_id, "name": name},
            )
        ).scalar_one()
    )


async def _job_row(db_session, arena_id: int, *, parser_key: str = "test_parser", config: dict | None = None) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, :pkey, true, 'daily', :next_run, CAST(:cfg AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "pkey": parser_key,
                    "next_run": _FINISHED - timedelta(minutes=1),
                    "cfg": json.dumps(config or {"horizon_days": 14, "timezone": "Europe/Minsk"}),
                },
            )
        ).scalar_one()
    )


async def _insert_row(db_session, arena_id: int, day: date, start: time, source_id: str) -> None:
    starts = _at(day, start)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local,
                price_adult_minor, currency_code, status, source_id, observed_at
            ) VALUES (
                :aid, 'public_skate', :s, :e, :ld, :sl, :el, 1000, 'BYN', 'active', :src, :obs
            )
            """
        ),
        {
            "aid": arena_id,
            "s": starts,
            "e": starts + timedelta(hours=1),
            "ld": day,
            "sl": start,
            "el": (datetime.combine(day, start) + timedelta(hours=1)).time(),
            "src": source_id,
            "obs": _FINISHED - timedelta(days=1),
        },
    )
    await db_session.flush()


async def _publish(db_session, *, arena_id: int, job_id: int, drafts, horizon_days: int) -> int:
    run = ScrapeRunRecord(
        job_id=job_id,
        arena_id=arena_id,
        parser_key="test_parser",
        status=RUN_STATUS_OK,
        slot_count=len(drafts),
        slots_dropped=0,
        error_message=None,
        started_at=_FINISHED - timedelta(seconds=30),
        finished_at=_FINISHED,
        publish_horizon_days=horizon_days,
        publish_timezone="Europe/Minsk",
    )
    run_id = await SqlAlchemyScrapeRunRecorder(db_session).record(run)
    assert run_id is not None
    return await SqlAlchemyIceSessionPublisher(db_session).publish(run, drafts, run_id=run_id)


async def _count(db_session, arena_id: int, day: date | None = None) -> int:
    sql = "SELECT count(*) FROM ice_sessions WHERE arena_id = :a"
    params: dict = {"a": arena_id}
    if day is not None:
        sql += " AND local_date = :d"
        params["d"] = day
    return int((await db_session.execute(text(sql), params)).scalar_one())


async def test_cancelled_last_session_today_is_removed(db_session, seed_city_id) -> None:
    """AC-1: в прогоне N сегодня был вечерний сеанс; в N+1 его нет, остальное сегодня прошло → удалён."""
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    tomorrow = _TODAY + timedelta(days=1)
    await _insert_row(db_session, arena_id, _TODAY, time(9, 0), "run:old:morning")  # уже прошёл
    await _insert_row(db_session, arena_id, _TODAY, time(20, 0), "run:old:evening")  # отменён источником

    await _publish(
        db_session, arena_id=arena_id, job_id=job_id, drafts=[_draft(arena_id, tomorrow, time(10, 0))], horizon_days=14
    )

    rows = (
        await db_session.execute(
            text("SELECT source_id FROM ice_sessions WHERE arena_id = :a AND local_date = :d ORDER BY 1"),
            {"a": arena_id, "d": _TODAY},
        )
    ).scalars().all()
    assert rows == ["run:old:morning"], "прошедший сеанс — история, отменённый будущий — удалён"
    assert await _count(db_session, arena_id, tomorrow) == 1


async def test_shrunk_horizon_drops_sessions_beyond_window(db_session, seed_city_id) -> None:
    """AC-2: горизонт 14 → 7: строки парсера на дни 8–14 удалены."""
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    for offset in (1, 7, 10, 13):
        await _insert_row(db_session, arena_id, _TODAY + timedelta(days=offset), time(12, 0), f"run:old:{offset}")

    drafts = [_draft(arena_id, _TODAY + timedelta(days=offset), time(12, 0)) for offset in (1, 6)]
    published = await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=drafts, horizon_days=7)

    assert published == 2
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=10)) == 0
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=13)) == 0
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=7)) == 0
    assert await _count(db_session, arena_id) == 2


async def test_manual_and_etalon_rows_survive_publish(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=2)
    await _insert_row(db_session, arena_id, day, time(12, 0), "admin")
    await _insert_row(db_session, arena_id, day, time(15, 0), "etalon_minsk_v1")

    # Черновик парсера на то же начало, что и ручная строка: индекс парсера их не сравнивает.
    await _publish(
        db_session, arena_id=arena_id, job_id=job_id, drafts=[_draft(arena_id, day, time(12, 0))], horizon_days=14
    )
    sources = (
        await db_session.execute(
            text("SELECT source_id FROM ice_sessions WHERE arena_id = :a ORDER BY source_id"),
            {"a": arena_id},
        )
    ).scalars().all()
    assert "admin" in sources and "etalon_minsk_v1" in sources
    assert len(sources) == 3


async def test_draft_beyond_horizon_published_twice_never_conflicts(db_session, seed_city_id) -> None:
    """Регрессия ревью #1: источник отдаёт месяц (пост Немана), горизонт 14, черновик на +20.

    Раньше окно удаления заканчивалось на max(даты выдачи) ≠ окну вставки, и второй
    прогон ловил UniqueViolation на старой строке → вечный publish_error.
    """
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    in_window = _draft(arena_id, _TODAY + timedelta(days=3), time(18, 0))
    far = _draft(arena_id, _TODAY + timedelta(days=20), time(18, 0))

    first = await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[in_window, far], horizon_days=14)
    second = await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[in_window, far], horizon_days=14)

    assert first == 1 and second == 1, "черновик за горизонтом отбрасывается до вставки"
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=20)) == 0
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=3)) == 1


async def test_far_row_already_in_db_does_not_freeze_publish(db_session, seed_city_id) -> None:
    """Старая строка на +20 (до выката окна) уже в базе: прогон не падает и чистит её."""
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    await _insert_row(db_session, arena_id, _TODAY + timedelta(days=20), time(18, 0), "test:legacy-far")

    far = _draft(arena_id, _TODAY + timedelta(days=20), time(18, 0))
    near = _draft(arena_id, _TODAY + timedelta(days=1), time(18, 0))
    await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[near, far], horizon_days=14)

    assert await _count(db_session, arena_id, _TODAY + timedelta(days=20)) == 0
    assert await _count(db_session, arena_id, _TODAY + timedelta(days=1)) == 1


async def test_scheduler_records_drop_reasons_and_counts(db_session, seed_city_id) -> None:
    """AC-3 через планировщик: 3 валидных + 1 на 150 мин → 3 опубликованы, slots_dropped=1 с причиной.

    Плюс прошедший слот (отброшен нормализатором) и слот за горизонтом: dropped считает всё,
    что извлечено, но не опубликовано, — без двойного счёта.
    """
    arena_id = await _arena(db_session, seed_city_id)
    day = (_TODAY + timedelta(days=1)).isoformat()
    events = [
        {"date": day, "start": "10:00", "end": "11:00", "adult": 1000, "id": "a"},
        {"date": day, "start": "12:00", "end": "13:00", "adult": 1000, "id": "b"},
        {"date": day, "start": "14:00", "end": "15:00", "adult": 1000, "id": "c"},
        {"date": day, "start": "16:00", "end": "18:30", "adult": 1000, "id": "long"},
        {"date": _TODAY.isoformat(), "start": "08:00", "end": "09:00", "adult": 1000, "id": "past"},
        {"date": (_TODAY + timedelta(days=30)).isoformat(), "start": "10:00", "end": "11:00", "adult": 1000, "id": "far"},
    ]
    widget = FakeJsonWidgetParser()
    job_id = await _job_row(
        db_session,
        arena_id,
        parser_key=widget.parser_key,
        config={
            "payload": {"events": events},
            "prices_already_minor": True,
            "timezone": "Europe/Minsk",
            "horizon_days": 14,
        },
    )
    registry = ParserRegistry()
    registry.register(widget)
    sched = IceIngestScheduler(
        store=SqlAlchemyParserJobStore(db_session),
        recorder=SqlAlchemyScrapeRunRecorder(db_session),
        registry=registry,
        publisher=SqlAlchemyIceSessionPublisher(db_session),
        max_jobs_per_tick=None,
    )
    outcomes = [o for o in await sched.run_due(_FINISHED) if o.job_id == job_id]
    assert len(outcomes) == 1
    run = outcomes[0]
    assert run.status == RUN_STATUS_OK
    assert run.slot_count == 3
    assert run.slots_dropped == 3  # длинный + прошедший + за горизонтом
    assert "отбраковано (длительность) 1" in (run.error_message or "")
    assert "в прошлом 1" in run.error_message
    assert "за горизонтом 1" in run.error_message
    assert await _count(db_session, arena_id) == 3
    persisted = (
        await db_session.execute(
            text("SELECT slots_found, slots_dropped, error_summary FROM ice_scrape_runs WHERE id = :id"),
            {"id": run.persisted_id},
        )
    ).one()
    assert persisted.slots_found == 3 and persisted.slots_dropped == 3
    assert "длительность" in persisted.error_summary


def test_publish_local_date_window_defaults() -> None:
    lo, hi = publish_local_date_window(now=_FINISHED, timezone_name="Europe/Minsk", horizon_days=7)
    assert lo == date(2026, 3, 15)
    assert hi == date(2026, 3, 21)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, DEFAULT_HORIZON_DAYS), ("abc", DEFAULT_HORIZON_DAYS), (0, 1), ("7", 7), (500, 62), (float("nan"), 14)],
)
def test_publish_horizon_days_parsing_never_raises(raw, expected) -> None:
    assert publish_horizon_days({"horizon_days": raw}) == expected
