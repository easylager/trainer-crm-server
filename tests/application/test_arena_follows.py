"""TASK-213: подписка на каток, диф сеансов, тихие часы, открытие."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth import get_client_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_follow_notify import (
    OPENING_TAIL,
    FollowBotBlocked,
    FollowSlot,
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

_MINSK = ZoneInfo("Europe/Minsk")
# Пятница 9 октября 2026, 14:10 по Минску.
_NOW = datetime(2026, 10, 9, 11, 10, tzinfo=timezone.utc)
_FRIDAY = date(2026, 10, 9)
_SATURDAY = date(2026, 10, 10)
_BASE = "https://glide.example"


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
        "Каток Ледовая площадка СДЮШОР открылся\n"
        "Первые сеансы: суббота 15:00 и 18:00.\n"
        + OPENING_TAIL
    )


async def _city(db_session) -> int:
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, is_active)
                    VALUES (:name, 'BY', true)
                    RETURNING id
                    """
                ),
                {"name": f"Город-{uuid.uuid4().hex[:8]}"},
            )
        ).scalar_one()
    )


async def _arena(db_session, city_id: int, name: str, *, mode: str = "auto") -> int:
    arena_id = int(
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
    await db_session.execute(
        text(
            """
            INSERT INTO arena_profiles (arena_id, city_id, slug, status, schedule_mode, timezone)
            VALUES (:aid, :cid, :slug, 'published', :mode, 'Europe/Minsk')
            """
        ),
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
                text(
                    """
                    SELECT id FROM arena_follows
                    WHERE telegram_id = :tg AND arena_id = :arena
                    """
                ),
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
        text(
            """
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                starts_at_local, ends_at_local, currency_code, status,
                source_id, observed_at, schedule_basis
            ) VALUES (
                :aid, 'public_skate', :s, :e, :d, :st, :et, 'BYN', 'active',
                :src, :obs, :basis
            )
            """
        ),
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


async def _publish(db_session, arena_id: int, drafts: list[CanonicalSlotDraft], *, finished_at: datetime = _NOW) -> None:
    job_id = (
        await db_session.execute(
            text("SELECT id FROM ice_parser_jobs WHERE arena_id = :aid"),
            {"aid": arena_id},
        )
    ).scalar()
    if job_id is None:
        job_id = (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_parser_jobs
                        (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                    VALUES (:aid, 'test_parser', true, 'daily', :next, CAST(:cfg AS jsonb))
                    RETURNING id
                    """
                ),
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
        await db_session.execute(
            text(
                """
                SELECT n.kind, n.status, n.payload, n.not_before, f.telegram_id, f.muted_at
                FROM arena_follow_notifications n
                JOIN arena_follows f ON f.id = n.follow_id
                WHERE f.arena_id = :arena
                ORDER BY f.telegram_id, n.id
                """
            ),
            {"arena": arena_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


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
async def test_projected_and_beyond_seven_days_do_not_notify(db_session) -> None:
    """AC-2: projected и сеанс за горизонтом 7 дней уведомления не дают."""
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Чижовка-арена")
    await _follow(db_session, arena_id, 2001)
    await _session_row(
        db_session, arena_id, _FRIDAY, time(19, 0), basis="projected", source_id="run:old:proj"
    )
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
        text(
            """
            UPDATE arena_follow_notifications
            SET status = 'sent', sent_at = :sent, not_before = :sent
            WHERE follow_id = :fid
            """
        ),
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
    assert await record_publish_follow_diff(
        db_session,
        arena_id=arena_id,
        before=empty,
        after=empty,
        past_ended_at=None,
        now=_NOW,
    ) == 0


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
    weekday = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")[
        tomorrow.weekday()
    ]
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
    assert await dispatch_due_follow_notifications(
        db_session, now=due_at, webapp_base_url=_BASE, send=_send
    ) == 1
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

    reply = await keep_following(
        db_session, telegram_id=6002, arena_id=arena_id, webapp_base_url=_BASE
    )
    assert "Продолжаем следить" in reply.text
    notes = await _notes(db_session, arena_id)

    async def _send(_item) -> None:
        return None

    await dispatch_due_follow_notifications(
        db_session, now=notes[0]["not_before"], webapp_base_url=_BASE, send=_send
    )
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
    row = (
        await db_session.execute(
            text(
                """
                SELECT f.muted_at, n.status
                FROM arena_follows f
                JOIN arena_follow_notifications n ON n.follow_id = f.id
                WHERE f.telegram_id = 7001
                """
            )
        )
    ).one()
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
            text(
                """
                SELECT count(*) FROM catalog_consumer_events
                WHERE kind = 'follow_created' AND arena_id = :arena
                """
            ),
            {"arena": arena_id},
        )
    ).scalar_one()
    assert int(events) == 1

    missing = await open_follow_from_start(
        db_session, telegram_id=8001, payload="follow_999999", webapp_base_url=_BASE
    )
    garbage = await open_follow_from_start(
        db_session, telegram_id=8001, payload="follow_nope", webapp_base_url=_BASE
    )
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
