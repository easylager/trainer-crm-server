"""TASK-213: подписка на каток, диф сеансов, тихие часы, открытие."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import src.application.arena_follow_notify as follow_notify
import src.bot.arena_follow_loop as arena_follow_loop
from src.api.app import app
from src.api.miniapp_auth import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_follow_notify import (
    OPENING_TAIL,
    FollowBotBlocked,
    FollowSlot,
    _upsert_pending,
    dispatch_due_follow_notifications,
    format_reopened_html,
    format_schedule_changed_html,
    record_publish_follow_diff,
)
from src.application.arena_follows import (
    BTN_KEEP,
    BTN_OPEN_SCHEDULE,
    BTN_SCHEDULE,
    BTN_UNFOLLOW,
    FOLLOW_MISSING_TEXT,
    follow_arena,
    open_follow_from_start,
    unfollow_command,
)
from src.application.arena_follows import SOURCE_MINIAPP
from src.application.arena_profile import apply_admin_arena_profile_patch
from src.ingestion.publish import SqlAlchemyIceSessionPublisher
from src.ingestion.scrape_runs import SqlAlchemyScrapeRunRecorder
from src.ingestion.types import RUN_STATUS_OK, CanonicalSlotDraft, ScrapeRunRecord
from src.shared.config import Settings

_MINSK = ZoneInfo("Europe/Minsk")
# Пятница 9 октября 2026, 14:10 по Минску.
_NOW = datetime(2026, 10, 9, 11, 10, tzinfo=timezone.utc)
_FRIDAY = date(2026, 10, 9)
_SATURDAY = date(2026, 10, 10)
_BASE = "https://glide.example"
_COMMITTED_TEST_CITIES: dict[int, list[int]] = {}


def _plain(value: str) -> str:
    return value.replace("<b>", "").replace("</b>", "")


def _at(day: date, hhmm: time) -> datetime:
    return datetime.combine(day, hhmm, tzinfo=_MINSK).astimezone(timezone.utc)


def _slot(day: date, start: time, end: time, kind: str = "public_skate") -> FollowSlot:
    return FollowSlot(local_date=day, starts_at_local=start, ends_at_local=end, kind=kind)


def test_schedule_change_text_matches_the_mock() -> None:
    text_html = format_schedule_changed_html(
        "Чижовка-арена",
        [_slot(_FRIDAY, time(19, 0), time(20, 0))],
        [_slot(_FRIDAY, time(20, 30), time(21, 30))],
        "14:10",
    )
    assert _plain(text_html) == (
        "Чижовка-арена: расписание изменилось\n"
        "Пятница: убрали сеанс 19:00.\n"
        "Добавили 20:30\u201321:30.\n"
        "С сайта катка, 14:10"
    )


def test_reopened_text_matches_the_mock() -> None:
    text_html = format_reopened_html(
        "Ледовая площадка СДЮШОР",
        [
            _slot(_SATURDAY, time(15, 0), time(16, 0)),
            _slot(_SATURDAY, time(18, 0), time(19, 0)),
        ],
    )
    assert _plain(text_html) == (
        "Каток Ледовая площадка СДЮШОР открылся\n" "Первые сеансы: суббота 15:00 и 18:00.\n" + OPENING_TAIL
    )


async def _city(db_session) -> int:
    return int(
        (
            await db_session.execute(
                text("""
                    INSERT INTO cities (name, country, is_active)
                    VALUES (:name, 'BY', true)
                    RETURNING id
                    """),
                {"name": f"Город-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar_one()
    )


async def _arena(db_session, city_id: int, name: str, *, mode: str = "auto") -> int:
    arena_id = int(
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
    await db_session.execute(
        text("""
            INSERT INTO arena_profiles (arena_id, city_id, slug, status, schedule_mode, timezone)
            VALUES (:aid, :cid, :slug, 'published', :mode, 'Europe/Minsk')
            """),
        {"aid": arena_id, "cid": city_id, "slug": f"rink-{uuid.uuid4().hex[:8]}", "mode": mode},
    )
    await db_session.flush()
    return arena_id


async def _follow(db_session, arena_id: int, telegram_id: int) -> int:
    reply = await follow_arena(
        db_session,
        telegram_id=telegram_id,
        arena_id=arena_id,
        source=SOURCE_MINIAPP,
        webapp_base_url=_BASE,
    )
    assert reply.found and reply.created
    return int(
        (
            await db_session.execute(
                text("""
                    SELECT id FROM arena_follows
                    WHERE telegram_id = :tg AND arena_id = :arena
                    """),
                {"tg": telegram_id, "arena": arena_id},
            )
        ).scalar_one()
    )


async def _session_row(
    db_session,
    arena_id: int,
    day: date,
    start: time,
    *,
    basis: str = "live",
    source_id: str,
    minutes: int = 60,
) -> None:
    starts = _at(day, start)
    await db_session.execute(
        text("""
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local, currency_code, status,
                source_id, observed_at, schedule_basis
            ) VALUES (
                :aid, 'public_skate', :s, :e, :d, :st, :et, 'BYN', 'active',
                :src, :obs, :basis
            )
            """),
        {
            "aid": arena_id,
            "s": starts,
            "e": starts + timedelta(minutes=minutes),
            "d": day,
            "st": start,
            "et": (datetime.combine(day, start) + timedelta(minutes=minutes)).time(),
            "src": source_id,
            "obs": _NOW,
            "basis": basis,
        },
    )


def _draft(arena_id: int, day: date, start: time, *, basis: str = "live", minutes: int = 60) -> CanonicalSlotDraft:
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
        observed_at=_NOW,
        valid_until=ends,
        source_id=f"test:{day.isoformat()}:{start.strftime('%H%M')}:{basis}",
        schedule_basis=basis,
    )


async def _publish(
    db_session, arena_id: int, drafts: list[CanonicalSlotDraft], *, finished_at: datetime = _NOW
) -> None:
    job_id = (
        await db_session.execute(
            text("SELECT id FROM ice_parser_jobs WHERE arena_id = :aid"),
            {"aid": arena_id},
        )
    ).scalar()
    if job_id is None:
        job_id = (
            await db_session.execute(
                text("""
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next, CAST(:cfg AS jsonb))
                    RETURNING id
                    """),
                {
                    "aid": arena_id,
                    "next": finished_at - timedelta(minutes=1),
                    "cfg": json.dumps({"horizon_days": 14, "timezone": "Europe/Minsk"}),
                },
            )
        ).scalar_one()
    job_id = int(job_id)
    run = ScrapeRunRecord(
        job_id=job_id,
        arena_id=arena_id,
        parser_key="test_parser",
        status=RUN_STATUS_OK,
        slot_count=len(drafts),
        slots_dropped=0,
        error_message=None,
        started_at=finished_at - timedelta(seconds=30),
        finished_at=finished_at,
        publish_horizon_days=14,
        publish_timezone="Europe/Minsk",
    )
    run_id = await SqlAlchemyScrapeRunRecorder(db_session).record(run)
    assert run_id is not None
    await SqlAlchemyIceSessionPublisher(db_session).publish(run, drafts, run_id=run_id)


async def _notes(db_session, arena_id: int) -> list[dict]:
    rows = (
        (
            await db_session.execute(
                text("""
                SELECT n.kind, n.status, n.payload, n.not_before, f.telegram_id, f.muted_at
                FROM arena_follow_notifications n
                JOIN arena_follows f ON f.id = n.follow_id
                WHERE f.arena_id = :arena
                ORDER BY f.telegram_id, n.id
                """),
                {"arena": arena_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


@pytest.fixture
async def committed_db():
    """Independent PostgreSQL sessions; commits are real, not db_session savepoints."""
    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    city_ids: list[int] = []
    _COMMITTED_TEST_CITIES[id(factory)] = city_ids
    try:
        yield factory
    finally:
        if city_ids:
            async with factory() as cleanup:
                await cleanup.execute(
                    text("""
                        DELETE FROM catalog_consumer_events WHERE arena_id IN (
                            SELECT id FROM arenas WHERE city_id = ANY(:city_ids)
                        )
                        """),
                    {"city_ids": city_ids},
                )
                await cleanup.execute(
                    text("""
                        DELETE FROM arena_follow_notifications
                        WHERE follow_id IN (
                            SELECT f.id FROM arena_follows f JOIN arenas a ON a.id = f.arena_id
                            WHERE a.city_id = ANY(:city_ids)
                        )
                        """),
                    {"city_ids": city_ids},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM arena_follows WHERE arena_id IN (SELECT id FROM arenas WHERE city_id = ANY(:city_ids))"
                    ),
                    {"city_ids": city_ids},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM ice_sessions WHERE arena_id IN (SELECT id FROM arenas WHERE city_id = ANY(:city_ids))"
                    ),
                    {"city_ids": city_ids},
                )
                await cleanup.execute(
                    text(
                        "DELETE FROM arena_profiles WHERE arena_id IN (SELECT id FROM arenas WHERE city_id = ANY(:city_ids))"
                    ),
                    {"city_ids": city_ids},
                )
                await cleanup.execute(text("DELETE FROM arenas WHERE city_id = ANY(:city_ids)"), {"city_ids": city_ids})
                await cleanup.execute(text("DELETE FROM cities WHERE id = ANY(:city_ids)"), {"city_ids": city_ids})
                await cleanup.commit()
        _COMMITTED_TEST_CITIES.pop(id(factory), None)
        await engine.dispose()


async def _committed_arena(factory, *, mode: str = "auto", telegram_ids: tuple[int, ...] = ()):
    async with factory() as session:
        city_id = await _city(session)
        _COMMITTED_TEST_CITIES[id(factory)].append(city_id)
        arena_id = await _arena(session, city_id, f"Тестовый каток {uuid.uuid4().hex[:8]}", mode=mode)
        follow_ids = [await _follow(session, arena_id, telegram_id) for telegram_id in telegram_ids]
        await session.commit()
    return city_id, arena_id, follow_ids


async def _insert_notification(
    session,
    *,
    follow_id: int,
    kind: str,
    payload: dict,
    now: datetime,
    status: str = "pending",
    not_before: datetime | None = None,
    created_at: datetime | None = None,
    claimed_at: datetime | None = None,
    attempts: int = 0,
) -> int:
    return int(
        (
            await session.execute(
                text("""
                    INSERT INTO arena_follow_notifications
                        (follow_id, kind, payload, not_before, created_at, status, attempts, claimed_at)
                    VALUES
                        (:fid, :kind, CAST(:payload AS jsonb), :not_before, :created_at, :status, :attempts, :claimed_at)
                    RETURNING id
                    """),
                {
                    "fid": follow_id,
                    "kind": kind,
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "not_before": not_before or now,
                    "created_at": created_at or now,
                    "status": status,
                    "attempts": attempts,
                    "claimed_at": claimed_at,
                },
            )
        ).scalar_one()
    )


def _schedule_payload(removed: list[FollowSlot], added: list[FollowSlot], *, hhmm: str = "14:10") -> dict:
    def _encode(slots: list[FollowSlot]) -> list[dict[str, str]]:
        return [
            {
                "local_date": slot.local_date.isoformat(),
                "starts_at_local": slot.starts_at_local.strftime("%H:%M"),
                "ends_at_local": slot.ends_at_local.strftime("%H:%M"),
                "kind": slot.kind,
            }
            for slot in slots
        ]

    return {
        "removed": _encode(removed),
        "added": _encode(added),
        "hhmm": hhmm,
        "text": "placeholder, rendered by dispatcher",
    }


def _unique_telegram_id() -> int:
    return 6_000_000_000 + uuid.uuid4().int % 999_999_999


@pytest.mark.asyncio
async def test_stale_sending_merges_pending_and_dispatches_other_follow(committed_db) -> None:
    _city_id, _arena_id, (first_follow, other_follow) = await _committed_arena(
        committed_db, telegram_ids=(10_001, 10_002)
    )
    now = _NOW + timedelta(minutes=30)
    removed_old = _slot(_FRIDAY, time(19, 0), time(20, 0))
    added_old = _slot(_FRIDAY, time(20, 30), time(21, 30))
    removed_new = _slot(_SATURDAY, time(18, 0), time(19, 0))
    added_new = _slot(_SATURDAY, time(19, 30), time(20, 30))
    async with committed_db() as session:
        old_id = await _insert_notification(
            session,
            follow_id=first_follow,
            kind="schedule_changed",
            payload=_schedule_payload([removed_old], [added_old]),
            now=now,
            status="sending",
            not_before=now - timedelta(minutes=1),
            created_at=now - timedelta(hours=1),
            claimed_at=now - timedelta(minutes=11),
            attempts=4,
        )
        await _insert_notification(
            session,
            follow_id=first_follow,
            kind="schedule_changed",
            payload=_schedule_payload([removed_new], [added_new]),
            now=now,
            not_before=now + timedelta(minutes=10),
            created_at=now - timedelta(minutes=5),
            attempts=2,
        )
        await _insert_notification(
            session,
            follow_id=other_follow,
            kind="schedule_changed",
            payload=_schedule_payload([], [added_old]),
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        await session.commit()

    sent = []

    async def send(item) -> None:
        sent.append(item)

    async with committed_db() as session:
        delivered = await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=send)
    assert delivered == 1
    assert [item.follow_id for item in sent] == [other_follow]

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT id, follow_id, kind, status, payload, attempts
                    FROM arena_follow_notifications
                    WHERE follow_id = ANY(:fids)
                    ORDER BY id
                    """),
                    {"fids": [first_follow, other_follow]},
                )
            )
            .mappings()
            .all()
        )
    first_rows = [row for row in rows if row["follow_id"] == first_follow]
    assert len(first_rows) == 2
    old_row = next(row for row in first_rows if row["id"] == old_id)
    pending = next(row for row in first_rows if row["status"] == "pending")
    assert old_row["status"] == "merged"
    assert pending["attempts"] == 4
    assert {slot["starts_at_local"] for slot in pending["payload"]["removed"]} == {"19:00", "18:00"}
    assert {slot["starts_at_local"] for slot in pending["payload"]["added"]} == {"20:30", "19:30"}
    other_row = next(row for row in rows if row["follow_id"] == other_follow)
    assert other_row["status"] == "sent"


@pytest.mark.asyncio
async def test_failed_send_merges_schedule_published_while_sending(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(10_003,))
    now = _NOW + timedelta(minutes=30)
    old_removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    old_added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    new_added = _slot(_SATURDAY, time(16, 0), time(17, 0))
    async with committed_db() as session:
        old_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([old_removed], [old_added]),
            now=now,
            not_before=now - timedelta(minutes=1),
            attempts=3,
        )
        await session.commit()

    async def send(_item) -> None:
        async with committed_db() as publisher:
            await _insert_notification(
                publisher,
                follow_id=follow_id,
                kind="schedule_changed",
                payload=_schedule_payload([], [new_added], hhmm="14:45"),
                now=now,
                not_before=now + timedelta(minutes=5),
                created_at=now + timedelta(minutes=1),
            )
            await publisher.commit()
        raise RuntimeError("Telegram is temporarily unavailable")

    async with committed_db() as session:
        assert await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=send) == 0

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT id, status, payload, attempts, not_before
                    FROM arena_follow_notifications WHERE follow_id = :fid ORDER BY id
                    """),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2
    old = next(row for row in rows if row["id"] == old_id)
    pending = next(row for row in rows if row["status"] == "pending")
    assert old["status"] == "merged"
    assert pending["attempts"] == 4
    assert {slot["starts_at_local"] for slot in pending["payload"]["removed"]} == {"19:00"}
    assert {slot["starts_at_local"] for slot in pending["payload"]["added"]} == {"20:30", "16:00"}
    assert pending["payload"]["hhmm"] == "14:45"
    assert pending["not_before"] >= now + timedelta(minutes=5)

    sent = []

    async def succeed(item) -> None:
        sent.append(item)

    async with committed_db() as session:
        assert (
            await dispatch_due_follow_notifications(
                session, now=now + timedelta(minutes=6), webapp_base_url=_BASE, send=succeed
            )
            == 1
        )
    assert len(sent) == 1
    assert "16:00\u201317:00" in sent[0].text


@pytest.mark.asyncio
async def test_successful_reopened_merges_returned_schedule_row(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(10_004,))
    now = _NOW + timedelta(minutes=30)
    open_slot = _slot(_SATURDAY, time(15, 0), time(16, 0))
    removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    async with committed_db() as session:
        reopened_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="reopened",
            payload={
                "slots": [
                    {
                        "local_date": _SATURDAY.isoformat(),
                        "starts_at_local": "15:00",
                        "ends_at_local": "16:00",
                        "kind": "public_skate",
                    }
                ],
                "keep": False,
                "text": "reopened",
            },
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        schedule_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([removed], [added]),
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        await session.commit()

    sent = []

    async def send(item) -> None:
        sent.append(item)
        async with committed_db() as publisher:
            await _insert_notification(
                publisher,
                follow_id=follow_id,
                kind="schedule_changed",
                payload=_schedule_payload([], [open_slot], hhmm="14:45"),
                now=now,
                not_before=now + timedelta(minutes=10),
                created_at=now + timedelta(minutes=1),
            )
            await publisher.commit()

    async with committed_db() as session:
        assert await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=send) == 1

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT id, kind, status, payload, attempts
                    FROM arena_follow_notifications WHERE follow_id = :fid ORDER BY id
                    """),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
        muted_at = (
            await session.execute(text("SELECT muted_at FROM arena_follows WHERE id = :fid"), {"fid": follow_id})
        ).scalar_one()
    reopened = next(row for row in rows if row["id"] == reopened_id)
    old_schedule = next(row for row in rows if row["id"] == schedule_id)
    pending = next(row for row in rows if row["status"] == "pending")
    assert reopened["status"] == "sent"
    assert old_schedule["status"] == "merged"
    assert pending["kind"] == "schedule_changed"
    assert {slot["starts_at_local"] for slot in pending["payload"]["removed"]} == {"19:00"}
    assert {slot["starts_at_local"] for slot in pending["payload"]["added"]} == {"20:30", "15:00"}
    assert muted_at is not None
    assert [item.kind for item in sent] == ["reopened"]


@pytest.mark.asyncio
async def test_upsert_pending_conflict_merges_slots_on_postgres(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(10_005,))
    now = _NOW
    removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    added_old = _slot(_FRIDAY, time(20, 30), time(21, 30))
    added_new = _slot(_SATURDAY, time(16, 0), time(17, 0))
    async with committed_db() as session:
        await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([removed], [added_old]),
            now=now,
            created_at=now - timedelta(minutes=10),
            attempts=5,
        )
        await session.commit()

    async with committed_db() as session:
        await _upsert_pending(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [added_new], hhmm="14:45"),
            not_before=now + timedelta(minutes=2),
            created_at=now + timedelta(minutes=1),
        )
        await session.commit()

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT status, payload, attempts, created_at
                    FROM arena_follow_notifications WHERE follow_id = :fid
                    """),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempts"] == 5
    assert rows[0]["created_at"] == now - timedelta(minutes=10)
    assert {slot["starts_at_local"] for slot in rows[0]["payload"]["removed"]} == {"19:00"}
    assert {slot["starts_at_local"] for slot in rows[0]["payload"]["added"]} == {"20:30", "16:00"}
    assert rows[0]["payload"]["hhmm"] == "14:45"


@pytest.mark.asyncio
async def test_publisher_waits_for_follow_lock_then_merges(committed_db) -> None:
    _city_id, arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(10_006,))
    first_removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    middle = _slot(_FRIDAY, time(20, 30), time(21, 30))
    final = _slot(_FRIDAY, time(21, 0), time(22, 0))
    async with committed_db() as session:
        await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([first_removed], [middle]),
            now=_NOW,
        )
        await session.commit()

    locker = committed_db()
    await locker.execute(text("SELECT id FROM arena_follows WHERE id = :fid FOR UPDATE"), {"fid": follow_id})
    publisher_finished = asyncio.Event()

    async def publish() -> None:
        async with committed_db() as publisher:
            await record_publish_follow_diff(
                publisher,
                arena_id=arena_id,
                before={middle.key: middle},
                after={final.key: final},
                past_ended_at=_NOW - timedelta(days=1),
                now=_NOW + timedelta(minutes=10),
            )
            await publisher.commit()
        publisher_finished.set()

    task = asyncio.create_task(publish())
    await asyncio.sleep(0.1)
    waited_for_lock = not publisher_finished.is_set()
    await locker.commit()
    await task
    await locker.close()
    assert waited_for_lock

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT status, payload FROM arena_follow_notifications WHERE follow_id = :fid"),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert [slot["starts_at_local"] for slot in rows[0]["payload"]["removed"]] == ["19:00"]
    assert [slot["starts_at_local"] for slot in rows[0]["payload"]["added"]] == ["21:00"]


@pytest.mark.asyncio
async def test_publish_and_admin_reopen_serialize_and_preserve_both_slot_sets(committed_db, monkeypatch) -> None:
    _city_id, arena_id, (follow_id,) = await _committed_arena(
        committed_db, mode="season_closed", telegram_ids=(10_007,)
    )
    await_day = _FRIDAY
    async with committed_db() as session:
        await _session_row(session, arena_id, await_day, time(15, 0), source_id="admin-reopen:1500")
        await _session_row(session, arena_id, _SATURDAY, time(18, 0), source_id="admin-reopen:1800")
        await session.commit()

    publish_slot = _slot(_FRIDAY + timedelta(days=2), time(11, 0), time(12, 0))
    metadata_ready = asyncio.Event()
    allow_metadata = asyncio.Event()
    original_meta = follow_notify._arena_meta
    publisher_task = None

    async def delayed_meta(session, target_arena_id):
        if asyncio.current_task() is publisher_task:
            metadata_ready.set()
            await allow_metadata.wait()
        return await original_meta(session, target_arena_id)

    monkeypatch.setattr(follow_notify, "_arena_meta", delayed_meta)

    async def publish() -> None:
        async with committed_db() as session:
            await record_publish_follow_diff(
                session,
                arena_id=arena_id,
                before={},
                after={publish_slot.key: publish_slot},
                past_ended_at=_NOW - timedelta(days=20),
                now=_NOW,
            )
            await session.commit()

    publisher_task = asyncio.create_task(publish())
    await asyncio.wait_for(metadata_ready.wait(), timeout=2)

    async def admin_reopen() -> None:
        async with committed_db() as session:
            await apply_admin_arena_profile_patch(session, arena_id, {"schedule_mode": "auto"})
            await session.commit()

    admin_task = asyncio.create_task(admin_reopen())
    await asyncio.sleep(0.1)
    admin_waited_for_follow_lock = not admin_task.done()
    allow_metadata.set()
    results = await asyncio.gather(publisher_task, admin_task, return_exceptions=True)
    assert all(not isinstance(result, BaseException) for result in results), results
    assert admin_waited_for_follow_lock

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT kind, status, payload FROM arena_follow_notifications WHERE follow_id = :fid"),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["kind"] == "reopened"
    assert rows[0]["status"] == "pending"
    assert {slot["starts_at_local"] for slot in rows[0]["payload"]["slots"]} == {
        "11:00",
        "15:00",
        "18:00",
    }


@pytest.mark.asyncio
async def test_unsubscribe_waits_for_publish_and_other_follower_is_queued(committed_db, monkeypatch) -> None:
    _city_id, arena_id, (unsubscribed_follow, other_follow) = await _committed_arena(
        committed_db, telegram_ids=(10_008, 10_009)
    )
    removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    metadata_ready = asyncio.Event()
    allow_metadata = asyncio.Event()
    original_meta = follow_notify._arena_meta
    publisher_task = None

    async def delayed_meta(session, target_arena_id):
        if asyncio.current_task() is publisher_task:
            metadata_ready.set()
            await allow_metadata.wait()
        return await original_meta(session, target_arena_id)

    monkeypatch.setattr(follow_notify, "_arena_meta", delayed_meta)

    async def publish() -> None:
        async with committed_db() as session:
            await record_publish_follow_diff(
                session,
                arena_id=arena_id,
                before={removed.key: removed},
                after={added.key: added},
                past_ended_at=_NOW - timedelta(days=1),
                now=_NOW,
            )
            await session.commit()

    publisher_task = asyncio.create_task(publish())
    await asyncio.wait_for(metadata_ready.wait(), timeout=2)

    async def unsubscribe() -> None:
        async with committed_db() as session:
            await session.execute(text("DELETE FROM arena_follows WHERE id = :fid"), {"fid": unsubscribed_follow})
            await session.commit()

    unsubscribe_task = asyncio.create_task(unsubscribe())
    await asyncio.sleep(0.1)
    unsubscribe_waited_for_follow_lock = not unsubscribe_task.done()
    allow_metadata.set()
    results = await asyncio.gather(publisher_task, unsubscribe_task, return_exceptions=True)
    assert all(not isinstance(result, BaseException) for result in results), results
    assert unsubscribe_waited_for_follow_lock

    async with committed_db() as session:
        queued = (
            (
                await session.execute(
                    text("SELECT status FROM arena_follow_notifications WHERE follow_id = :fid"),
                    {"fid": other_follow},
                )
            )
            .scalars()
            .all()
        )
        gone = (
            await session.execute(text("SELECT 1 FROM arena_follows WHERE id = :fid"), {"fid": unsubscribed_follow})
        ).first()
    assert queued == ["pending"]
    assert gone is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("age", "expected_status"),
    [
        (timedelta(minutes=1), "sending"),
        (timedelta(minutes=11), "pending"),
        (None, "pending"),
    ],
)
async def test_recovery_respects_claim_lease_age(committed_db, age, expected_status) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    now = _NOW + timedelta(minutes=30)
    async with committed_db() as session:
        notification_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [_slot(_FRIDAY, time(20, 30), time(21, 30))]),
            now=now,
            status="sending",
            not_before=now + timedelta(hours=1),
            claimed_at=now - age if age is not None else None,
        )
        await session.commit()

    async def should_not_send(_item) -> None:
        raise AssertionError("future notification was sent during lease recovery")

    async with committed_db() as session:
        await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=should_not_send)
    async with committed_db() as session:
        status = (
            await session.execute(
                text("SELECT status FROM arena_follow_notifications WHERE id = :id"),
                {"id": notification_id},
            )
        ).scalar_one()
    assert status == expected_status


@pytest.mark.asyncio
async def test_recovered_reopened_loses_claim_without_duplicate_send(committed_db, caplog) -> None:
    _city_id, arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    now = _NOW + timedelta(minutes=30)
    slot = _slot(_SATURDAY, time(15, 0), time(16, 0))
    async with committed_db() as session:
        notification_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="reopened",
            payload={
                "slots": [
                    {
                        "local_date": slot.local_date.isoformat(),
                        "starts_at_local": "15:00",
                        "ends_at_local": "16:00",
                        "kind": "public_skate",
                    }
                ],
                "keep": False,
                "text": "reopened",
            },
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        await session.commit()

    sent = []

    async def take_over_claim(item) -> None:
        sent.append(item)
        async with committed_db() as takeover:
            claim_time = (
                await takeover.execute(
                    text("SELECT claimed_at FROM arena_follow_notifications WHERE id = :id"),
                    {"id": notification_id},
                )
            ).scalar_one()
            assert claim_time is not None
            await takeover.execute(
                text("""
                    UPDATE arena_follow_notifications
                    SET status = 'pending', claimed_at = NULL
                    WHERE id = :id AND status = 'sending'
                    """),
                {"id": notification_id},
            )
            await takeover.commit()

    async with committed_db() as session:
        assert (
            await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=take_over_claim) == 1
        )
    async with committed_db() as session:
        status, muted_at = (
            await session.execute(
                text("""
                    SELECT n.status, f.muted_at
                    FROM arena_follow_notifications n
                    JOIN arena_follows f ON f.id = n.follow_id
                    WHERE n.id = :id
                    """),
                {"id": notification_id},
            )
        ).one()
    assert status == "pending"
    assert muted_at is not None
    assert "lost sending claim" in caplog.text.lower()

    async with committed_db() as session:
        metric = (
            await session.execute(
                text("""
                    SELECT payload FROM catalog_consumer_events
                    WHERE arena_id = :arena AND kind = 'follow_notified'
                      AND payload->>'notification_id' = :notification_id
                    ORDER BY id DESC LIMIT 1
                    """),
                {"arena": arena_id, "notification_id": str(notification_id)},
            )
        ).scalar_one()
    assert metric["claim_lost"] is True

    async with committed_db() as session:
        assert (
            await dispatch_due_follow_notifications(
                session, now=now + timedelta(minutes=1), webapp_base_url=_BASE, send=take_over_claim
            )
            == 0
        )
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_long_telegram_retry_after_requeues_without_sleeping(committed_db, monkeypatch) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    now = _NOW + timedelta(minutes=30)
    slot = _slot(_FRIDAY, time(20, 30), time(21, 30))
    async with committed_db() as session:
        await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [slot]),
            now=now,
            not_before=now - timedelta(minutes=1),
        )
        await session.commit()

    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(arena_follow_loop, "asyncio", SimpleNamespace(sleep=fake_sleep))

    class RetryBot:
        async def send_message(self, *, chat_id, text, reply_markup) -> None:
            raise TelegramRetryAfter(
                method=SendMessage(chat_id=chat_id, text=text),
                message="Too Many Requests",
                retry_after=45,
            )

    async def send(item) -> None:
        await arena_follow_loop._send(RetryBot(), item)

    async with committed_db() as session:
        assert await dispatch_due_follow_notifications(session, now=now, webapp_base_url=_BASE, send=send) == 0
    assert sleeps == []
    async with committed_db() as session:
        status, not_before = (
            await session.execute(
                text("SELECT status, not_before FROM arena_follow_notifications WHERE follow_id = :fid"),
                {"fid": follow_id},
            )
        ).one()
    assert status == "pending"
    assert not_before >= now + timedelta(seconds=45)


@pytest.mark.asyncio
async def test_quiet_hours_recovery_merges_but_does_not_send(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    # 23:30 in Minsk.
    night = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)
    old_added = _slot(_SATURDAY, time(15, 0), time(16, 0))
    pending_added = _slot(_SATURDAY, time(18, 0), time(19, 0))
    async with committed_db() as session:
        old_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [old_added]),
            now=night,
            status="sending",
            not_before=night - timedelta(minutes=1),
            claimed_at=night - timedelta(minutes=11),
        )
        await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [pending_added]),
            now=night,
            not_before=night - timedelta(minutes=1),
            created_at=night - timedelta(minutes=1),
        )
        await session.commit()

    sent = []

    async def send(item) -> None:
        sent.append(item)

    async with committed_db() as session:
        assert await dispatch_due_follow_notifications(session, now=night, webapp_base_url=_BASE, send=send) == 0
    assert sent == []
    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("""
                    SELECT id, status, payload, not_before
                    FROM arena_follow_notifications WHERE follow_id = :fid ORDER BY id
                    """),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    old = next(row for row in rows if row["id"] == old_id)
    pending = next(row for row in rows if row["status"] == "pending")
    assert old["status"] == "merged"
    assert len(rows) == 2
    assert pending["not_before"] >= datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)
    assert {slot["starts_at_local"] for slot in pending["payload"]["added"]} == {"15:00", "18:00"}


@pytest.mark.asyncio
async def test_parallel_upserts_merge_after_real_unique_conflict(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    now = _NOW
    old_added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    new_added = _slot(_SATURDAY, time(16, 0), time(17, 0))
    first = committed_db()
    await _insert_notification(
        first,
        follow_id=follow_id,
        kind="schedule_changed",
        payload=_schedule_payload([], [old_added]),
        now=now,
    )

    async def concurrent_upsert() -> None:
        async with committed_db() as second:
            await _upsert_pending(
                second,
                follow_id=follow_id,
                kind="schedule_changed",
                payload=_schedule_payload([], [new_added], hhmm="14:45"),
                not_before=now + timedelta(minutes=5),
                created_at=now + timedelta(minutes=1),
            )
            await second.commit()

    task = asyncio.create_task(concurrent_upsert())
    await asyncio.sleep(0.1)
    was_waiting_on_unique_or_follow_lock = not task.done()
    await first.commit()
    await first.close()
    await task
    assert was_waiting_on_unique_or_follow_lock

    async with committed_db() as session:
        rows = (
            (
                await session.execute(
                    text("SELECT status, payload FROM arena_follow_notifications WHERE follow_id = :fid"),
                    {"fid": follow_id},
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert {slot["starts_at_local"] for slot in rows[0]["payload"]["added"]} == {"20:30", "16:00"}


@pytest.mark.asyncio
async def test_merged_status_is_allowed_by_notification_constraint(committed_db) -> None:
    _city_id, _arena_id, (follow_id,) = await _committed_arena(committed_db, telegram_ids=(_unique_telegram_id(),))
    async with committed_db() as session:
        row_id = await _insert_notification(
            session,
            follow_id=follow_id,
            kind="schedule_changed",
            payload=_schedule_payload([], [_slot(_FRIDAY, time(20, 30), time(21, 30))]),
            now=_NOW,
            status="merged",
        )
        await session.commit()
    async with committed_db() as session:
        assert (
            await session.execute(
                text("SELECT status FROM arena_follow_notifications WHERE id = :id"),
                {"id": row_id},
            )
        ).scalar_one() == "merged"


@pytest.mark.asyncio
async def test_publish_queues_one_change_per_follower_and_repeat_is_silent(db_session) -> None:
    """AC-1: пропал 19:00, появился 20:30 — одно уведомление каждому; повтор той же публикации — ноль."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 1001)
    await _follow(db_session, arena_id, 1002)
    await _session_row(db_session, arena_id, _FRIDAY, time(19, 0), source_id="run:old:1900")

    drafts = [_draft(arena_id, _FRIDAY, time(20, 30))]
    await _publish(db_session, arena_id, drafts)
    notes = await _notes(db_session, arena_id)
    assert len(notes) == 2
    assert {row["telegram_id"] for row in notes} == {1001, 1002}
    expected = (
        "Чижовка-арена: расписание изменилось\n"
        "Пятница: убрали сеанс 19:00.\n"
        "Добавили 20:30\u201321:30.\n"
        "С сайта катка, 14:10"
    )
    for row in notes:
        assert row["kind"] == "schedule_changed"
        assert _plain(row["payload"]["text"]) == expected

    await _publish(db_session, arena_id, drafts)
    assert len(await _notes(db_session, arena_id)) == 2

    sent: list = []

    async def _send(item) -> None:
        sent.append(item)

    delivered = await dispatch_due_follow_notifications(
        db_session,
        now=_NOW + timedelta(minutes=30),
        webapp_base_url=_BASE,
        send=_send,
    )
    assert delivered == 2
    assert len(sent) == 2
    for item in sent:
        assert _plain(item.text) == expected
        labels = [button.text for button in item.buttons]
        assert labels == [BTN_OPEN_SCHEDULE, BTN_UNFOLLOW]
        assert item.buttons[0].web_app_url is not None
        assert item.buttons[0].web_app_url.startswith(f"{_BASE}/p/")


@pytest.mark.asyncio
async def test_follow_diff_failure_does_not_roll_back_publish(db_session, monkeypatch) -> None:
    """Настоящий unique violation внутри savepoint не откатывает опубликованные сеансы."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 1001)
    await _session_row(db_session, arena_id, _FRIDAY, time(19, 0), source_id="run:old:1900")
    original = follow_notify.record_publish_follow_diff
    integrity_seen = []

    async def _insert_duplicate(session, *args, **kwargs) -> None:
        await original(session, *args, **kwargs)
        try:
            await session.execute(
                text("""
                    INSERT INTO arena_follow_notifications
                        (follow_id, kind, payload, not_before, created_at, status)
                    SELECT id, 'schedule_changed', '{}'::jsonb, :now, :now, 'pending'
                    FROM arena_follows WHERE arena_id = :arena LIMIT 1
                    """),
                {"now": _NOW, "arena": arena_id},
            )
        except IntegrityError:
            integrity_seen.append(True)
            raise
        raise AssertionError("duplicate pending insert unexpectedly succeeded")

    monkeypatch.setattr(
        "src.application.arena_follow_notify.record_publish_follow_diff",
        _insert_duplicate,
    )
    await _publish(db_session, arena_id, [_draft(arena_id, _FRIDAY, time(20, 30))])

    starts = (
        (
            await db_session.execute(
                text("""
                SELECT starts_at_local
                FROM ice_sessions
                WHERE arena_id = :aid AND status = 'active'
                ORDER BY starts_at_local
                """),
                {"aid": arena_id},
            )
        )
        .scalars()
        .all()
    )
    assert integrity_seen == [True]
    assert starts == [time(20, 30)]
    assert await _notes(db_session, arena_id) == []


@pytest.mark.asyncio
async def test_projected_and_beyond_seven_days_do_not_notify(db_session) -> None:
    """AC-2: projected и сеанс за горизонтом 7 дней уведомления не дают."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 2001)
    await _session_row(db_session, arena_id, _FRIDAY, time(19, 0), basis="projected", source_id="run:old:proj")
    far = _FRIDAY + timedelta(days=11)
    await _session_row(db_session, arena_id, far, time(19, 0), source_id="run:old:far")
    await _publish(
        db_session,
        arena_id,
        [
            _draft(arena_id, _FRIDAY, time(20, 30), basis="projected"),
            _draft(arena_id, far, time(21, 0)),
        ],
    )
    assert await _notes(db_session, arena_id) == []


@pytest.mark.asyncio
async def test_quiet_hours_and_six_hour_gap(db_session) -> None:
    """AC-3: ночью копим до 08:00; после отправки следующее изменение ждёт 6 часов."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    follow_id = await _follow(db_session, arena_id, 3001)
    night = datetime(2026, 10, 9, 20, 30, tzinfo=timezone.utc)  # 23:30 Минск
    before = {_slot(_SATURDAY, time(19, 0), time(20, 0)).key: _slot(_SATURDAY, time(19, 0), time(20, 0))}
    after = {_slot(_SATURDAY, time(20, 30), time(21, 30)).key: _slot(_SATURDAY, time(20, 30), time(21, 30))}
    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before=before,
        after=after,
        past_ended_at=night - timedelta(days=1),
        now=night,
    )
    notes = await _notes(db_session, arena_id)
    assert len(notes) == 1
    morning = datetime(2026, 10, 10, 5, 0, tzinfo=timezone.utc)  # 08:00 Минск
    assert notes[0]["not_before"] >= morning
    sent: list = []

    async def _send(item) -> None:
        sent.append(item)

    assert await dispatch_due_follow_notifications(db_session, now=night, webapp_base_url=_BASE, send=_send) == 0
    assert sent == []

    await db_session.execute(
        text("""
            UPDATE arena_follow_notifications
            SET status = 'sent', sent_at = :sent, not_before = :sent
            WHERE follow_id = :fid
            """),
        {"sent": datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc), "fid": follow_id},
    )
    day = datetime(2026, 10, 10, 7, 0, tzinfo=timezone.utc)  # 10:00 Минск, час после sent
    later = {_slot(_SATURDAY, time(21, 0), time(22, 0)).key: _slot(_SATURDAY, time(21, 0), time(22, 0))}
    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before=after,
        after=later,
        past_ended_at=day - timedelta(days=1),
        now=day,
    )
    pending = [row for row in await _notes(db_session, arena_id) if row["status"] == "pending"]
    assert len(pending) == 1
    assert pending[0]["not_before"] >= datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    assert await dispatch_due_follow_notifications(db_session, now=day, webapp_base_url=_BASE, send=_send) == 0
    assert sent == []


@pytest.mark.asyncio
async def test_changes_inside_thirty_minutes_merge(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 4001)
    first_removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    first_added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    second_added = _slot(_FRIDAY, time(21, 0), time(22, 0))
    empty: dict = {}
    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before={first_removed.key: first_removed},
        after={first_added.key: first_added},
        past_ended_at=_NOW - timedelta(days=2),
        now=_NOW,
    )
    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before={first_added.key: first_added},
        after={first_added.key: first_added, second_added.key: second_added},
        past_ended_at=_NOW - timedelta(days=2),
        now=_NOW + timedelta(minutes=10),
    )
    notes = await _notes(db_session, arena_id)
    assert len(notes) == 1
    plain = _plain(notes[0]["payload"]["text"])
    assert "Пятница: убрали сеанс 19:00." in plain
    assert "20:30\u201321:30" in plain
    assert "21:00\u201322:00" in plain
    assert notes[0]["not_before"] >= _NOW + timedelta(minutes=30)
    assert (
        await record_publish_follow_diff(
            db_session,
            arena_id=arena_id,
            before=empty,
            after=empty,
            past_ended_at=None,
            now=_NOW,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_first_fill_is_not_a_change_and_fourteen_day_gap_reopens(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 5001)
    added = _slot(_FRIDAY, time(19, 0), time(20, 0))
    assert (
        await record_publish_follow_diff(
            db_session,
            arena_id=arena_id,
            before={},
            after={added.key: added},
            past_ended_at=None,
            now=_NOW,
        )
        == 0
    )
    assert await _notes(db_session, arena_id) == []

    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before={},
        after={added.key: added},
        past_ended_at=_NOW - timedelta(days=20),
        now=_NOW,
    )
    notes = await _notes(db_session, arena_id)
    assert len(notes) == 1
    assert notes[0]["kind"] == "reopened"
    assert "открылся" in notes[0]["payload"]["text"]


@pytest.mark.asyncio
async def test_season_closed_to_auto_opens_and_mutes_without_keep(db_session) -> None:
    """AC-4: переход season_closed → auto с сеансами даёт «открылся» и гасит подписку."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Ледовая площадка СДЮШОР", mode="season_closed")
    await _follow(db_session, arena_id, 6001)
    tomorrow = datetime.now(timezone.utc).astimezone(_MINSK).date() + timedelta(days=1)
    weekday = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")[tomorrow.weekday()]
    await _session_row(db_session, arena_id, tomorrow, time(15, 0), source_id="run:open:1500")
    await _session_row(db_session, arena_id, tomorrow, time(18, 0), source_id="run:open:1800")
    await apply_admin_arena_profile_patch(db_session, arena_id, {"schedule_mode": "auto"})
    await db_session.commit()
    notes = await _notes(db_session, arena_id)
    assert len(notes) == 1
    assert notes[0]["kind"] == "reopened"
    plain = _plain(notes[0]["payload"]["text"])
    assert plain.startswith("Каток Ледовая площадка СДЮШОР открылся")
    assert f"Первые сеансы: {weekday} 15:00 и 18:00." in plain
    assert OPENING_TAIL in plain

    sent: list = []

    async def _send(item) -> None:
        sent.append(item)

    due_at = notes[0]["not_before"]
    assert await dispatch_due_follow_notifications(db_session, now=due_at, webapp_base_url=_BASE, send=_send) == 1
    assert [button.text for button in sent[0].buttons] == [BTN_SCHEDULE, BTN_KEEP]
    muted = (
        await db_session.execute(
            text("SELECT muted_at FROM arena_follows WHERE telegram_id = 6001 AND arena_id = :arena"),
            {"arena": arena_id},
        )
    ).scalar()
    assert muted is not None


@pytest.mark.asyncio
async def test_keep_following_prevents_mute(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Ледовая площадка СДЮШОР", mode="season_closed")
    await _follow(db_session, arena_id, 6002)
    tomorrow = datetime.now(timezone.utc).astimezone(_MINSK).date() + timedelta(days=1)
    await _session_row(db_session, arena_id, tomorrow, time(15, 0), source_id="run:keep:1500")
    await apply_admin_arena_profile_patch(db_session, arena_id, {"schedule_mode": "auto"})
    await db_session.commit()
    from src.application.arena_follows import keep_following

    reply = await keep_following(db_session, telegram_id=6002, arena_id=arena_id, webapp_base_url=_BASE)
    assert "Продолжаем следить" in reply.text
    notes = await _notes(db_session, arena_id)

    async def _send(_item) -> None:
        return None

    await dispatch_due_follow_notifications(db_session, now=notes[0]["not_before"], webapp_base_url=_BASE, send=_send)
    muted = (
        await db_session.execute(
            text("SELECT muted_at FROM arena_follows WHERE telegram_id = 6002 AND arena_id = :arena"),
            {"arena": arena_id},
        )
    ).scalar()
    assert muted is None


@pytest.mark.asyncio
async def test_blocked_bot_mutes_the_follow(db_session) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 7001)
    removed = _slot(_FRIDAY, time(19, 0), time(20, 0))
    added = _slot(_FRIDAY, time(20, 30), time(21, 30))
    await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before={removed.key: removed},
        after={added.key: added},
        past_ended_at=_NOW - timedelta(days=1),
        now=_NOW,
    )

    async def _send(_item) -> None:
        raise FollowBotBlocked("bot was blocked by the user")

    assert (
        await dispatch_due_follow_notifications(
            db_session, now=_NOW + timedelta(minutes=30), webapp_base_url=_BASE, send=_send
        )
        == 0
    )
    row = (await db_session.execute(text("""
                SELECT f.muted_at, n.status
                FROM arena_follows f
                JOIN arena_follow_notifications n ON n.follow_id = f.id
                WHERE f.telegram_id = 7001
                """))).one()
    assert row[0] is not None
    assert row[1] == "muted"


@pytest.mark.asyncio
async def test_follow_start_is_idempotent_and_invalid_is_polite(db_session) -> None:
    """AC-5: follow_{id} один раз; невалидный id — вежливый ответ."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена", mode="season_closed")
    first = await open_follow_from_start(
        db_session, telegram_id=8001, payload=f"follow_{arena_id}", webapp_base_url=_BASE
    )
    second = await open_follow_from_start(
        db_session, telegram_id=8001, payload=f"follow_{arena_id}", webapp_base_url=_BASE
    )
    assert first.created is True
    assert second.created is False
    assert first.text == second.text
    assert "или когда каток откроется" in first.text
    assert [button.text for button in first.buttons] == [BTN_SCHEDULE, BTN_UNFOLLOW]
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM arena_follows WHERE telegram_id = 8001 AND arena_id = :arena"),
            {"arena": arena_id},
        )
    ).scalar_one()
    assert int(count) == 1
    events = (
        await db_session.execute(
            text("""
                SELECT count(*) FROM catalog_consumer_events
                WHERE kind = 'follow_created' AND arena_id = :arena
                """),
            {"arena": arena_id},
        )
    ).scalar_one()
    assert int(events) == 1

    missing = await open_follow_from_start(db_session, telegram_id=8001, payload="follow_999999", webapp_base_url=_BASE)
    garbage = await open_follow_from_start(db_session, telegram_id=8001, payload="follow_nope", webapp_base_url=_BASE)
    assert missing.text == FOLLOW_MISSING_TEXT
    assert garbage.text == FOLLOW_MISSING_TEXT
    assert missing.buttons == ()

    stopped = await unfollow_command(db_session, telegram_id=8001)
    assert "Больше не следим" in stopped.text
    left = (
        await db_session.execute(
            text("SELECT count(*) FROM arena_follows WHERE telegram_id = 8001"),
        )
    ).scalar_one()
    assert int(left) == 0


@pytest.mark.asyncio
async def test_webapp_post_follow_is_idempotent(db_session, app_use_test_db) -> None:
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    app.dependency_overrides[get_client_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=9001
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/webapp/client/arena-follows", json={"arena_id": arena_id})
            second = await client.post("/api/webapp/client/arena-follows", json={"arena_id": arena_id})
            missing = await client.post("/api/webapp/client/arena-follows", json={"arena_id": 999999})
            removed = await client.delete(f"/api/webapp/client/arena-follows/{arena_id}")
        assert first.status_code == 200
        assert first.json()["created"] is True
        assert first.json()["following"] is True
        assert second.json()["created"] is False
        assert missing.status_code == 404
        assert removed.status_code == 200
        assert removed.json()["following"] is False
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bare = await client.post("/api/webapp/client/arena-follows", json={"arena_id": arena_id})
    assert bare.status_code == 401


def _principal(user_id: int):
    return lambda: MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)


@pytest.mark.asyncio
async def test_webapp_get_follow_status_is_per_user(db_session, app_use_test_db) -> None:
    """Не подписан / подписан / отписан; чужой пользователь чужую подписку не видит."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    path = f"/api/webapp/client/arena-follows/{arena_id}"
    app.dependency_overrides[get_client_miniapp_principal] = _principal(9001)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            absent = await client.get(path)
            await client.post("/api/webapp/client/arena-follows", json={"arena_id": arena_id})
            active = await client.get(path)
            await db_session.execute(
                text("""
                    UPDATE arena_follows
                    SET muted_at = now()
                    WHERE telegram_id = 9001 AND arena_id = :aid
                    """),
                {"aid": arena_id},
            )
            muted = await client.get(path)
            await client.delete(path)
            gone = await client.get(path)
            await client.post("/api/webapp/client/arena-follows", json={"arena_id": arena_id})
            app.dependency_overrides[get_client_miniapp_principal] = _principal(9002)
            stranger = await client.get(path)
        assert absent.status_code == 200
        assert absent.json() == {"arena_id": arena_id, "following": False, "muted": False}
        assert active.json() == {"arena_id": arena_id, "following": True, "muted": False}
        assert muted.json() == {"arena_id": arena_id, "following": True, "muted": True}
        assert gone.json() == {"arena_id": arena_id, "following": False, "muted": False}
        assert stranger.json() == {"arena_id": arena_id, "following": False, "muted": False}
    finally:
        app.dependency_overrides.pop(get_client_miniapp_principal, None)
