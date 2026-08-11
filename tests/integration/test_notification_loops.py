"""
Integration tests for notification batch helpers (Telegram mocked).
Requires test DB: DATABASE_URL, alembic upgrade head.
"""
from datetime import date, time, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_city_id, require_seed_service_id
from tests.integration.test_booking_use_cases import (
    _create_client,
    _create_trainer_and_slot,
)
from src.application.booking_use_cases import (
    create_booking,
    mark_booking_completed_and_notify,
)
from src.bot.notification_loops import (
    process_booking_complete_round,
    process_cancel_notifications_batch,
    process_completed_feedback_batch,
    process_request_notifications_batch,
    process_response_notifications_batch,
)


async def _insert_cancel_notification(
    db_session,
    booking_id: int,
    client_tid: int,
    slot_date: date,
    start_t: time,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO booking_cancel_notifications
                (booking_id, client_telegram_id, slot_date, start_time, trainer_display_name)
            VALUES (:bid, :tid, :d, :st, 'T')
            RETURNING id
            """
        ),
        {"bid": booking_id, "tid": client_tid, "d": slot_date, "st": start_t},
    )
    (nid,) = r.fetchone()
    await db_session.commit()
    return nid


@pytest.mark.asyncio
async def test_cancel_batch_marks_sent_only_after_telegram_ok(db_session) -> None:
    tomorrow = date.today() + timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, tomorrow, time(10, 0), time(11, 0)
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    await _insert_cancel_notification(db_session, booking_id, tid, tomorrow, time(10, 0))

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("telegram down"))
    await process_cancel_notifications_batch(bot, db_session)
    r = await db_session.execute(
        text("SELECT sent_at FROM booking_cancel_notifications WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert r.scalar() is None

    bot.send_message = AsyncMock(return_value=None)
    await process_cancel_notifications_batch(bot, db_session)
    r2 = await db_session.execute(
        text("SELECT sent_at FROM booking_cancel_notifications WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert r2.scalar() is not None


@pytest.mark.asyncio
async def test_response_batch_marks_sent_only_after_telegram_ok(db_session) -> None:
    """client_request_responses.client_notified_at set only after successful send."""
    city_id = await require_seed_city_id(db_session)
    service_id = await require_seed_service_id(db_session)
    tid = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tid)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (:tid, 'C', :phone, :pn) RETURNING id
            """
        ),
        {"tid": tid, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'R', 30)"
        ),
        {"tid": trainer_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO client_requests (client_id, city_id, service_id, status, trainer_id)
            VALUES (:cid, :city, :sid, 'new', :tid) RETURNING id
            """
        ),
        {"cid": client_id, "city": city_id, "sid": service_id, "tid": trainer_id},
    )
    (request_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO client_request_responses (client_request_id, trainer_id)
            VALUES (:rid, :tid) RETURNING id
            """
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    (response_id,) = r.fetchone()
    await db_session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("fail"))
    await process_response_notifications_batch(bot, db_session)
    r = await db_session.execute(
        text("SELECT client_notified_at FROM client_request_responses WHERE id = :id"),
        {"id": response_id},
    )
    assert r.scalar() is None

    bot.send_message = AsyncMock(return_value=None)
    await process_response_notifications_batch(bot, db_session)
    r2 = await db_session.execute(
        text("SELECT client_notified_at FROM client_request_responses WHERE id = :id"),
        {"id": response_id},
    )
    assert r2.scalar() is not None


@pytest.mark.asyncio
async def test_request_batch_marks_sent_only_after_telegram_ok(db_session) -> None:
    """Pending request notify: INSERT into client_request_notifications only after successful send."""
    city_id = await require_seed_city_id(db_session)
    service_id = await require_seed_service_id(db_session)
    tr_tid = 888_000_000 + (unique_test_telegram_id() % 99_999_999)
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (telegram_id, status) VALUES (:tg, 'active') RETURNING id
            """
        ),
        {"tg": tr_tid},
    )
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'A', 'B', 25)"
        ),
        {"tid": trainer_id},
    )
    tid_client = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tid_client)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (:tid, 'C', :phone, :pn) RETURNING id
            """
        ),
        {"tid": tid_client, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO client_requests (client_id, city_id, service_id, status, trainer_id)
            VALUES (:cid, :city, :sid, 'new', :tid) RETURNING id
            """
        ),
        {"cid": client_id, "city": city_id, "sid": service_id, "tid": trainer_id},
    )
    (request_id,) = r.fetchone()
    await db_session.commit()

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("fail"))
    await process_request_notifications_batch(bot, db_session)
    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM client_request_notifications
            WHERE client_request_id = :rid AND trainer_id = :tid
            """
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    assert r.scalar() == 0

    bot.send_message = AsyncMock(return_value=None)
    await process_request_notifications_batch(bot, db_session)
    r2 = await db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM client_request_notifications
            WHERE client_request_id = :rid AND trainer_id = :tid
            """
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    assert r2.scalar() == 1


@pytest.mark.asyncio
async def test_completed_feedback_marks_sent_only_after_telegram_ok(db_session, monkeypatch) -> None:
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    r = await db_session.execute(
        text(
            "SELECT id FROM booking_completed_notifications WHERE booking_id = :bid"
        ),
        {"bid": booking_id},
    )
    (notif_id,) = r.fetchone()

    tr_telegram = 777_000_000 + (unique_test_telegram_id() % 99_999_999)
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tid WHERE id = :id"),
        {"tid": tr_telegram, "id": trainer_id},
    )
    await db_session.commit()

    # Time-independent test: completed-feedback loop also checks trainer push window.
    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("fail"))
    await process_completed_feedback_batch(bot, db_session)
    r = await db_session.execute(
        text("SELECT trainer_sent_at FROM booking_completed_notifications WHERE id = :id"),
        {"id": notif_id},
    )
    assert r.scalar() is None

    bot.send_message = AsyncMock(return_value=None)
    await process_completed_feedback_batch(bot, db_session)
    r2 = await db_session.execute(
        text("SELECT trainer_sent_at FROM booking_completed_notifications WHERE id = :id"),
        {"id": notif_id},
    )
    assert r2.scalar() is not None


@pytest.mark.asyncio
async def test_completed_feedback_timeout_keeps_claim_no_retry(db_session, monkeypatch) -> None:
    """Timeout after deliver risk: keep trainer_sent_at so the loop does not spam duplicates."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    r = await db_session.execute(
        text(
            "SELECT id FROM booking_completed_notifications WHERE booking_id = :bid"
        ),
        {"bid": booking_id},
    )
    (notif_id,) = r.fetchone()

    tr_telegram = 777_000_000 + (unique_test_telegram_id() % 99_999_999)
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tid WHERE id = :id"),
        {"tid": tr_telegram, "id": trainer_id},
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=RuntimeError("HTTP Client says - Request timeout error"))
    await process_completed_feedback_batch(bot, db_session)
    r = await db_session.execute(
        text("SELECT trainer_sent_at FROM booking_completed_notifications WHERE id = :id"),
        {"id": notif_id},
    )
    assert r.scalar() is not None

    bot.send_message.reset_mock()
    await process_completed_feedback_batch(bot, db_session)
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_completed_feedback_button_user_invalid_retries_without_markup(
    db_session, monkeypatch
) -> None:
    """BUTTON_USER_INVALID must not leave the row pending forever."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    r = await db_session.execute(
        text(
            "SELECT id FROM booking_completed_notifications WHERE booking_id = :bid"
        ),
        {"bid": booking_id},
    )
    (notif_id,) = r.fetchone()

    tr_telegram = 777_000_000 + (unique_test_telegram_id() % 99_999_999)
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tid WHERE id = :id"),
        {"tid": tr_telegram, "id": trainer_id},
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )

    calls: list[object] = []

    async def _send(**kwargs):
        calls.append(kwargs.get("reply_markup"))
        if kwargs.get("reply_markup") is not None:
            raise RuntimeError("Telegram server says - Bad Request: BUTTON_USER_INVALID")
        return None

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=_send)
    await process_completed_feedback_batch(bot, db_session)
    assert len(calls) >= 2
    assert calls[-1] is None
    r2 = await db_session.execute(
        text("SELECT trainer_sent_at FROM booking_completed_notifications WHERE id = :id"),
        {"id": notif_id},
    )
    assert r2.scalar() is not None


@pytest.mark.asyncio
async def test_completed_feedback_row_when_client_has_no_telegram(db_session) -> None:
    """CRM-only client (no Telegram): still enqueue trainer «Занятие завершено»; no-pass alone is not enough."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tid)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, 'No', 'Name', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    r = await db_session.execute(
        text(
            """
            SELECT id, client_telegram_id FROM booking_completed_notifications
            WHERE booking_id = :bid
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    assert row is not None
    assert row[1] is None


@pytest.mark.asyncio
async def test_booking_complete_round_sets_client_push_timestamp_after_send(db_session, monkeypatch) -> None:
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)

    await db_session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = NULL WHERE id = :id"
        ),
        {"id": booking_id},
    )
    await db_session.commit()

    # Time-independent test: completion loop is gated by global quiet hours.
    monkeypatch.setattr("src.bot.notification_loops.is_within_notification_hours", lambda: True)
    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )

    client_bot = MagicMock()
    client_bot.send_message = AsyncMock(return_value=None)
    trainer_bot = MagicMock()
    trainer_bot.send_message = AsyncMock(return_value=None)

    await process_booking_complete_round(client_bot, trainer_bot)

    r = await db_session.execute(
        text(
            "SELECT client_booking_completed_push_sent_at FROM bookings WHERE id = :id"
        ),
        {"id": booking_id},
    )
    assert r.scalar() is not None
    assert client_bot.send_message.await_count >= 1


@pytest.mark.asyncio
async def test_client_completed_push_timeout_keeps_claim_no_retry(db_session, monkeypatch) -> None:
    """Client completion timeout must keep sent_at so the loop does not spam."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    await db_session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = NULL WHERE id = :id"
        ),
        {"id": booking_id},
    )
    await db_session.commit()

    monkeypatch.setattr("src.bot.notification_loops.is_within_notification_hours", lambda: True)
    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "src.bot.notification_loops._maybe_send_session_milestone_pushes",
        AsyncMock(return_value=None),
    )

    client_bot = MagicMock()
    client_bot.send_message = AsyncMock(
        side_effect=RuntimeError("HTTP Client says - Request timeout error")
    )
    trainer_bot = MagicMock()
    trainer_bot.send_message = AsyncMock(return_value=None)

    await process_booking_complete_round(client_bot, trainer_bot)
    r = await db_session.execute(
        text(
            "SELECT client_booking_completed_push_sent_at FROM bookings WHERE id = :id"
        ),
        {"id": booking_id},
    )
    assert r.scalar() is not None

    client_bot.send_message.reset_mock()
    await process_booking_complete_round(client_bot, trainer_bot)
    client_bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_client_completed_push_button_user_invalid_retries_without_markup(
    db_session, monkeypatch
) -> None:
    """Client BUTTON_USER_INVALID must not leave completion push pending forever."""
    yesterday = date.today() - timedelta(days=1)
    trainer_id, slot_id, service_id = await _create_trainer_and_slot(
        db_session, yesterday, time(10, 0), time(11, 0), status="available"
    )
    tid = unique_test_telegram_id()
    client_id = await _create_client(db_session, tid)
    booking_id, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
    )
    assert booking_id is not None
    await mark_booking_completed_and_notify(db_session, booking_id)
    await db_session.execute(
        text(
            "UPDATE bookings SET client_booking_completed_push_sent_at = NULL WHERE id = :id"
        ),
        {"id": booking_id},
    )
    await db_session.commit()

    monkeypatch.setattr("src.bot.notification_loops.is_within_notification_hours", lambda: True)
    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        "src.bot.notification_loops._maybe_send_session_milestone_pushes",
        AsyncMock(return_value=None),
    )

    calls: list[object] = []

    async def _send(**kwargs):
        calls.append(kwargs.get("reply_markup"))
        if kwargs.get("reply_markup") is not None:
            raise RuntimeError("Telegram server says - Bad Request: BUTTON_USER_INVALID")
        return None

    client_bot = MagicMock()
    client_bot.send_message = AsyncMock(side_effect=_send)
    trainer_bot = MagicMock()
    trainer_bot.send_message = AsyncMock(return_value=None)

    await process_booking_complete_round(client_bot, trainer_bot)
    assert len(calls) >= 2
    assert calls[-1] is None
    r = await db_session.execute(
        text(
            "SELECT client_booking_completed_push_sent_at FROM bookings WHERE id = :id"
        ),
        {"id": booking_id},
    )
    assert r.scalar() is not None
