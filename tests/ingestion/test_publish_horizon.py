"""TASK-187: delete window follows job horizon, not draft min/max dates."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.publish_horizon import publish_local_date_window
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import CanonicalSlotDraft, RUN_STATUS_OK, ScrapeRunRecord

_MINSK = ZoneInfo("Europe/Minsk")
_FINISHED = datetime(2026, 3, 15, 20, 0, tzinfo=timezone.utc)  # 23:00 Europe/Minsk same calendar day


def _draft(
    arena_id: int,
    local_date: date,
    start: time,
    end: time,
    *,
    starts_utc: datetime,
    ends_utc: datetime,
) -> CanonicalSlotDraft:
    return CanonicalSlotDraft(
        arena_id=arena_id,
        kind="public_skate",
        starts_at_utc=starts_utc,
        ends_at_utc=ends_utc,
        local_date=local_date,
        starts_at_local=start,
        ends_at_local=end,
        price_adult_minor=1000,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status="active",
        observed_at=_FINISHED,
        valid_until=_FINISHED + timedelta(hours=6),
        source_id="test:slot",
    )


async def _arena_id(db_session) -> int:
    city = (await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))).scalar()
    if city is None:
        pytest.skip("need seed cities")
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, 'Лёд-187', 'ул. Тестовая, 1', true, true)
                    RETURNING id
                    """
                ),
                {"cid": int(city)},
            )
        ).scalar_one()
    )


async def _job_row(db_session, arena_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next_run, CAST(:cfg AS jsonb))
                    RETURNING id
                    """
                ),
                {
                    "aid": arena_id,
                    "next_run": _FINISHED - timedelta(minutes=1),
                    "cfg": json.dumps({"horizon_days": 14, "timezone": "Europe/Minsk"}),
                },
            )
        ).scalar_one()
    )


async def _publish(
    db_session,
    *,
    arena_id: int,
    job_id: int,
    drafts: list[CanonicalSlotDraft],
    horizon_days: int,
) -> None:
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
    recorder = SqlAlchemyScrapeRunRecorder(db_session)
    run_id = await recorder.record(run)
    assert run_id is not None
    publisher = SqlAlchemyIceSessionPublisher(db_session)
    await publisher.publish(run, drafts, run_id=run_id)


@pytest.mark.asyncio
async def test_publish_window_starts_today_not_min_draft_date(db_session) -> None:
    """AC-1: orphan today row is removed when new run only has tomorrow slots."""
    arena_id = await _arena_id(db_session)
    job_id = await _job_row(db_session, arena_id)
    today = _FINISHED.astimezone(_MINSK).date()
    tomorrow = today + timedelta(days=1)

    start_today = datetime(2026, 3, 15, 17, 0, tzinfo=_MINSK).astimezone(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local,
                price_adult_minor, currency_code, status, source_id, observed_at
            ) VALUES (
                :aid, 'public_skate', :s, :e, :ld,
                '17:00', '18:00',
                1000, 'BYN', 'active', 'run:old:today', :obs
            )
            """
        ),
        {
            "aid": arena_id,
            "s": start_today,
            "e": start_today + timedelta(hours=1),
            "ld": today,
            "obs": _FINISHED,
        },
    )
    await db_session.flush()

    start_tom = datetime(2026, 3, 16, 10, 0, tzinfo=_MINSK).astimezone(timezone.utc)
    drafts = [
        _draft(
            arena_id,
            tomorrow,
            time(10, 0),
            time(11, 0),
            starts_utc=start_tom,
            ends_utc=start_tom + timedelta(hours=1),
        )
    ]
    await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=drafts, horizon_days=14)

    left_today = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sessions WHERE arena_id = :a AND local_date = :d"),
            {"a": arena_id, "d": today},
        )
    ).scalar_one()
    assert int(left_today) == 0
    tomorrow_n = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sessions WHERE arena_id = :a AND local_date = :d"),
            {"a": arena_id, "d": tomorrow},
        )
    ).scalar_one()
    assert int(tomorrow_n) == 1


@pytest.mark.asyncio
async def test_shrunk_horizon_drops_sessions_beyond_window(db_session) -> None:
    """AC-2: horizon 7 removes parser slots on day 8+ even if a draft exists for today."""
    arena_id = await _arena_id(db_session)
    job_id = await _job_row(db_session, arena_id)
    today = _FINISHED.astimezone(_MINSK).date()
    far = today + timedelta(days=10)

    start_far = datetime.combine(far, time(12, 0), tzinfo=_MINSK).astimezone(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local,
                price_adult_minor, currency_code, status, source_id, observed_at
            ) VALUES (
                :aid, 'public_skate', :s, :e, :ld,
                '12:00', '13:00',
                1000, 'BYN', 'active', 'run:old:far', :obs
            )
            """
        ),
        {
            "aid": arena_id,
            "s": start_far,
            "e": start_far + timedelta(hours=1),
            "ld": far,
            "obs": _FINISHED,
        },
    )
    await db_session.flush()

    start_today = datetime.combine(today, time(9, 0), tzinfo=_MINSK).astimezone(timezone.utc)
    drafts = [
        _draft(
            arena_id,
            today,
            time(9, 0),
            time(10, 0),
            starts_utc=start_today,
            ends_utc=start_today + timedelta(hours=1),
        )
    ]
    await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=drafts, horizon_days=7)

    far_left = (
        await db_session.execute(
            text("SELECT count(*) FROM ice_sessions WHERE arena_id = :a AND local_date = :d"),
            {"a": arena_id, "d": far},
        )
    ).scalar_one()
    assert int(far_left) == 0


def test_publish_local_date_window_defaults() -> None:
    lo, hi = publish_local_date_window(
        now=_FINISHED,
        timezone_name="Europe/Minsk",
        horizon_days=7,
    )
    assert lo == date(2026, 3, 15)
    assert hi == date(2026, 3, 21)
