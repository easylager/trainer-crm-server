"""TASK-223: повторная публикация сохраняет ice_sessions.id слота.

Без локального Postgres эти тесты не запускаются; их гоняет CI (как
``test_publish_horizon.py``). Фикстуры те же: ``db_session`` + ``seed_city_id``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord

_MINSK = ZoneInfo("Europe/Minsk")
_FINISHED = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)  # 12:00 Минск
_TODAY = _FINISHED.astimezone(_MINSK).date()


def _at(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, tzinfo=_MINSK).astimezone(timezone.utc)


def _draft(
    arena_id: int,
    day: date,
    start: time,
    *,
    kind: str = "public_skate",
    minutes: int = 60,
    price: int = 1000,
    source_id: str | None = None,
    label: str | None = None,
    basis: str = "live",
    status: str = "active",
) -> CanonicalSlotDraft:
    starts = _at(day, start)
    ends = starts + timedelta(minutes=minutes)
    return CanonicalSlotDraft(
        arena_id=arena_id,
        kind=kind,
        starts_at_utc=starts,
        ends_at_utc=ends,
        local_date=day,
        starts_at_local=start,
        ends_at_local=ends.astimezone(_MINSK).time().replace(tzinfo=None),
        price_adult_minor=price,
        price_child_minor=None,
        price_rental_minor=None,
        currency_code="BYN",
        status=status,
        observed_at=_FINISHED,
        valid_until=ends,
        session_label=label,
        source_id=source_id if source_id is not None else f"test:{kind}:{day.isoformat()}:{start.isoformat()}",
        schedule_basis=basis,
    )


async def _arena(db_session, city_id: int) -> int:
    name = f"Лёд-223-{uuid.uuid4().hex[:8]}"
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                    VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
                    RETURNING id
                    """),
                {"cid": city_id, "name": name},
            )
        ).scalar_one()
    )


async def _job_row(db_session, arena_id: int) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next_run, CAST(:cfg AS jsonb))
                    RETURNING id
                    """),
                {
                    "aid": arena_id,
                    "next_run": _FINISHED - timedelta(minutes=1),
                    "cfg": json.dumps({"horizon_days": 14, "timezone": "Europe/Minsk"}),
                },
            )
        ).scalar_one()
    )


async def _insert_row(
    db_session,
    arena_id: int,
    day: date,
    start: time,
    source_id: str | None,
    *,
    kind: str = "public_skate",
    status: str = "active",
    price: int = 1000,
    minutes: int = 60,
) -> int:
    starts = _at(day, start)
    ends = starts + timedelta(minutes=minutes)
    session_id = int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO ice_sessions (
                        arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local,
                        price_adult_minor, price_minor, currency_code, status, source_id, observed_at
                    ) VALUES (
                        :aid, :kind, :s, :e, :ld, :sl, :el,
                        :price, :price, 'BYN', :status, :src, :obs
                    )
                    RETURNING id
                    """),
                {
                    "aid": arena_id,
                    "kind": kind,
                    "s": starts,
                    "e": ends,
                    "ld": day,
                    "sl": start,
                    "el": ends.astimezone(_MINSK).time().replace(tzinfo=None),
                    "price": price,
                    "status": status,
                    "src": source_id,
                    "obs": _FINISHED - timedelta(days=1),
                },
            )
        ).scalar_one()
    )
    await db_session.flush()
    return session_id


async def _publish(db_session, *, arena_id: int, job_id: int, drafts) -> int:
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
        publish_horizon_days=14,
        publish_timezone="Europe/Minsk",
    )
    run_id = await SqlAlchemyScrapeRunRecorder(db_session).record(run)
    assert run_id is not None
    return await SqlAlchemyIceSessionPublisher(db_session).publish(run, drafts, run_id=run_id)


async def _rows(db_session, arena_id: int) -> list[dict]:
    result = await db_session.execute(
        text("""
            SELECT id, kind, starts_at_utc, ends_at_utc, local_date, price_adult_minor, price_minor,
                   status, source_id, session_label, schedule_basis
            FROM ice_sessions
            WHERE arena_id = :a
            ORDER BY id
            """),
        {"a": arena_id},
    )
    return [dict(row) for row in result.mappings()]


def _slot(row: dict) -> tuple[str, datetime]:
    return _instant_slot(str(row["kind"]), row["starts_at_utc"])


def _slot_of(draft: CanonicalSlotDraft) -> tuple[str, datetime]:
    return _instant_slot(draft.kind, draft.starts_at_utc)


def _instant_slot(kind: str, start: datetime) -> tuple[str, datetime]:
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc)
    return (kind, start)


def _same_instant(left: datetime, right: datetime) -> bool:
    return _instant_slot("", left)[1] == _instant_slot("", right)[1]


@pytest.mark.asyncio
async def test_republish_keeps_ids_and_applies_the_diff(db_session, seed_city_id) -> None:
    """Два прогона с теми же слотами — те же id; цена меняется на месте; исчезший слот удалён; новый — новый id."""
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=1)
    past_id = await _insert_row(db_session, arena_id, _TODAY, time(9, 0), "run:old:morning")

    skate = _draft(arena_id, day, time(18, 0), kind="public_skate", price=1000, label="вечер")
    hockey = _draft(arena_id, day, time(18, 0), kind="hockey_practice", price=1500, label="охм")

    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[skate, hockey]) == 2
    first = {_slot(row): row for row in await _rows(db_session, arena_id)}
    skate_id = first[_slot_of(skate)]["id"]
    hockey_id = first[_slot_of(hockey)]["id"]
    assert skate_id != hockey_id
    assert first[("public_skate", _at(_TODAY, time(9, 0)))]["id"] == past_id

    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[skate, hockey]) == 2
    second = {_slot(row): row for row in await _rows(db_session, arena_id)}
    assert second[_slot_of(skate)]["id"] == skate_id
    assert second[_slot_of(hockey)]["id"] == hockey_id

    repriced = _draft(
        arena_id,
        day,
        time(18, 0),
        kind="public_skate",
        minutes=90,
        price=2500,
        label="вечер+",
        basis="projected",
        source_id="test:repriced",
    )
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[repriced, hockey]) == 2
    priced = {_slot(row): row for row in await _rows(db_session, arena_id)}
    skate_row = priced[_slot_of(repriced)]
    assert skate_row["id"] == skate_id
    assert skate_row["price_adult_minor"] == 2500
    assert skate_row["price_minor"] == 2500
    assert skate_row["session_label"] == "вечер+"
    assert skate_row["schedule_basis"] == "projected"
    assert skate_row["source_id"] == "test:repriced"
    assert _same_instant(skate_row["ends_at_utc"], repriced.ends_at_utc)
    assert priced[_slot_of(hockey)]["id"] == hockey_id

    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[repriced]) == 1
    left = {_slot(row): row for row in await _rows(db_session, arena_id)}
    assert _slot_of(hockey) not in left
    assert left[_slot_of(repriced)]["id"] == skate_id
    assert left[("public_skate", _at(_TODAY, time(9, 0)))]["id"] == past_id

    added = _draft(arena_id, day, time(20, 0), kind="public_skate", price=3000)
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[repriced, added]) == 2
    final = {_slot(row): row for row in await _rows(db_session, arena_id)}
    assert final[_slot_of(repriced)]["id"] == skate_id
    assert final[_slot_of(added)]["id"] not in {skate_id, hockey_id, past_id}


@pytest.mark.asyncio
async def test_admin_and_etalon_rows_keep_their_ids(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=2)
    admin_id = await _insert_row(db_session, arena_id, day, time(12, 0), "admin")
    etalon_id = await _insert_row(db_session, arena_id, day, time(15, 0), "etalon_minsk_v1")

    draft = _draft(arena_id, day, time(12, 0))
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[draft]) == 1
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[draft]) == 1

    rows = {row["source_id"]: row for row in await _rows(db_session, arena_id)}
    assert rows["admin"]["id"] == admin_id
    assert rows["etalon_minsk_v1"]["id"] == etalon_id
    assert rows[draft.source_id]["id"] not in {admin_id, etalon_id}
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_null_source_id_is_updated_or_deleted_like_the_old_filter(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=1)
    kept_id = await _insert_row(db_session, arena_id, day, time(18, 0), None, price=1000)
    orphan_id = await _insert_row(db_session, arena_id, day, time(19, 0), None)

    draft = _draft(arena_id, day, time(18, 0), price=1800, source_id="test:from-null")
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[draft]) == 1

    rows = await _rows(db_session, arena_id)
    ids = {row["id"] for row in rows}
    assert kept_id in ids
    assert orphan_id not in ids
    kept = next(row for row in rows if row["id"] == kept_id)
    assert kept["price_adult_minor"] == 1800
    assert kept["source_id"] == "test:from-null"


@pytest.mark.asyncio
async def test_expired_future_row_is_reactivated_in_place(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=1)
    session_id = await _insert_row(db_session, arena_id, day, time(18, 0), "run:old", status="expired", price=900)
    draft = _draft(arena_id, day, time(18, 0), price=1100, status="active")
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[draft]) == 1
    rows = await _rows(db_session, arena_id)
    assert len(rows) == 1
    assert rows[0]["id"] == session_id
    assert rows[0]["status"] == "active"
    assert rows[0]["price_adult_minor"] == 1100


@pytest.mark.asyncio
async def test_empty_drafts_do_not_wipe_existing_ids(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    day = _TODAY + timedelta(days=1)
    draft = _draft(arena_id, day, time(18, 0), price=1000)
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[draft]) == 1
    before = await _rows(db_session, arena_id)
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[]) == 0
    after = await _rows(db_session, arena_id)
    assert [(row["id"], row["price_adult_minor"]) for row in after] == [
        (row["id"], row["price_adult_minor"]) for row in before
    ]


@pytest.mark.asyncio
async def test_draft_beyond_horizon_does_not_churn_in_window_id(db_session, seed_city_id) -> None:
    arena_id = await _arena(db_session, seed_city_id)
    job_id = await _job_row(db_session, arena_id)
    near = _draft(arena_id, _TODAY + timedelta(days=3), time(18, 0))
    far = _draft(arena_id, _TODAY + timedelta(days=20), time(18, 0))
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[near, far]) == 1
    first_id = (await _rows(db_session, arena_id))[0]["id"]
    assert await _publish(db_session, arena_id=arena_id, job_id=job_id, drafts=[near, far]) == 1
    rows = await _rows(db_session, arena_id)
    assert len(rows) == 1
    assert rows[0]["id"] == first_id
    assert rows[0]["local_date"] == near.local_date
