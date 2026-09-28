"""
Хаб клиента: после первой записи тренер всегда остаётся «основным».

Продуктовое правило: записался к тренеру — тренер закрепляется основным и попадает
в «Сохранённые»; занятие прошло — тренер с хаба не исчезает. Раньше «Мой тренер» был
только вычислением по живым записям (INNER JOIN slots + узкий список статусов), поэтому
отменённый слот или снятое тренером занятие стирали связь, и клиенту снова предлагали
весь каталог.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.booking_use_cases import (
    client_ever_booked_primary_candidate,
    client_ever_booked_trainer_ids,
    client_latest_booking_primary_candidate,
    create_booking,
    mark_booking_completed_and_notify,
)
from src.application.client_trainer_edge_use_cases import get_edge as get_trainer_edge
from src.application.client_use_cases import get_or_create_client
from tests.api.test_webapp_client_miniapp_integration import (
    _create_trainer_online_with_slot,
    _fresh_client_telegram_id,
    _minsk_monday_reference,
    _require_seed_ids,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone


async def _ensure_client_session_row(db_session, telegram_id: int) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state)
            VALUES (:t, 'idle')
            ON CONFLICT (telegram_id) DO NOTHING
            """
        ),
        {"t": telegram_id},
    )
    await db_session.flush()


async def _edges_payload(telegram_id: int) -> dict:
    with patch_client_init_auth(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/client/trainer-edges",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _client_with_past_booking(db_session) -> tuple[int, int, int, int]:
    """Клиент с прошедшей записью у тренера. Возвращает (telegram_id, client_id, trainer_id, booking_id)."""
    ref_day, _ = _minsk_monday_reference()
    past_day = ref_day - timedelta(days=14)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=past_day, start_hours={14}
    )
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)
    client_id = await get_or_create_client(db_session, ctg, phone=phone, first_name="Клиент")
    await _ensure_client_session_row(db_session, ctg)
    booking_id, _ = await create_booking(
        db_session, slot_id, trainer_id, client_id, service_id, created_by_trainer=True
    )
    assert booking_id is not None
    await db_session.flush()
    return ctg, int(client_id), int(trainer_id), int(booking_id)


@pytest.mark.asyncio
async def test_primary_survives_trainer_removed_booking(app_use_test_db, db_session) -> None:
    """Тренер снял проведённое занятие из расписания — «Мой тренер» обязан остаться."""
    ctg, _client_id, trainer_id, booking_id = await _client_with_past_booking(db_session)
    await mark_booking_completed_and_notify(db_session, booking_id)
    await db_session.execute(
        text("UPDATE bookings SET status = 'trainer_removed' WHERE id = :b"), {"b": booking_id}
    )
    await db_session.flush()

    assert await client_latest_booking_primary_candidate(db_session, ctg) == (None, None)
    ever_tid, _ever_svc = await client_ever_booked_primary_candidate(db_session, ctg)
    assert ever_tid == trainer_id

    body = await _edges_payload(ctg)
    assert body["primary"] is not None, body
    assert int(body["primary"]["trainer_id"]) == trainer_id


@pytest.mark.asyncio
async def test_primary_survives_cancelled_slot(app_use_test_db, db_session) -> None:
    """Слот отменён тренером (status='cancelled') — история записи всё ещё держит тренера на хабе."""
    ctg, _client_id, trainer_id, booking_id = await _client_with_past_booking(db_session)
    await db_session.execute(
        text(
            """
            UPDATE slots SET status = 'cancelled'
            WHERE id = (SELECT slot_id FROM bookings WHERE id = :b)
            """
        ),
        {"b": booking_id},
    )
    await db_session.flush()

    assert await client_latest_booking_primary_candidate(db_session, ctg) == (None, None)
    body = await _edges_payload(ctg)
    assert body["primary"] is not None, body
    assert int(body["primary"]["trainer_id"]) == trainer_id


@pytest.mark.asyncio
async def test_ever_booked_trainer_lands_in_saved_page_past_bucket(
    app_use_test_db, db_session
) -> None:
    """
    Запись, созданную тренером в CRM, ребро не создаёт — но тренер обязан быть
    в «Мои тренеры» (bucket ``past``), а не пропадать вместе с отсутствующим ребром.
    """
    ctg, client_id, trainer_id, booking_id = await _client_with_past_booking(db_session)
    assert await get_trainer_edge(client_id, trainer_id, db_session) is None
    ever = await client_ever_booked_trainer_ids(db_session, ctg)
    assert [tid for tid, _svc in ever] == [trainer_id]

    body = await _edges_payload(ctg)
    # Тренер — основной, значит в past его быть не должно (без дублей).
    assert int(body["primary"]["trainer_id"]) == trainer_id
    assert trainer_id not in {int(e["trainer_id"]) for e in body.get("past") or []}

    # Как только основным становится другой тренер, прошлый уходит в past, а не в никуда.
    ref_day, _ = _minsk_monday_reference()
    other_tid, other_svc, other_slot = await _create_trainer_online_with_slot(
        db_session, slot_date=ref_day - timedelta(days=1), start_hours={9}
    )
    other_booking, _ = await create_booking(
        db_session, other_slot, other_tid, client_id, other_svc, created_by_trainer=True
    )
    assert other_booking is not None
    await db_session.flush()
    body2 = await _edges_payload(ctg)
    assert int(body2["primary"]["trainer_id"]) == other_tid
    assert trainer_id in {int(e["trainer_id"]) for e in body2.get("past") or []}


@pytest.mark.asyncio
async def test_completed_booking_fills_edge_history(app_use_test_db, db_session) -> None:
    """Проведённое занятие наполняет ``completed_count`` ребра (история «Мой тренер» на хабе)."""
    from src.application.client_trainer_edge_use_cases import record_booking_edge

    ctg, client_id, trainer_id, booking_id = await _client_with_past_booking(db_session)
    await record_booking_edge(client_id, ctg, trainer_id, session=db_session)
    await db_session.flush()

    await mark_booking_completed_and_notify(db_session, booking_id)
    edge = await get_trainer_edge(client_id, trainer_id, db_session)
    assert edge is not None
    assert int(edge["completed_count"]) == 1
    assert edge["last_completed_at"] is not None


@pytest.mark.asyncio
async def test_client_booking_pins_trainer_as_primary_and_saved(
    app_use_test_db, db_session
) -> None:
    """Запись из Mini App закрепляет тренера основным и складывает его в «Сохранённые»."""
    ref_day, ref_now = _minsk_monday_reference()
    future_day = ref_day + timedelta(days=4)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=future_day, start_hours={14}
    )
    _sid, city_id, arena_id = await _require_seed_ids(db_session)
    ctg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(ctg)

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with patch_client_init_auth(ctg):
        with patch("src.api.routes.webapp.Bot", return_value=mock_bot):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                sess_body: dict = {"city_id": city_id, "service_id": service_id, "trainer_id": trainer_id}
                if arena_id is not None:
                    sess_body["arena_id"] = arena_id
                await client.post(
                    "/api/webapp/client/session",
                    json=sess_body,
                    headers={"X-Telegram-Init-Data": "mock"},
                )
                with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                    "src.api.routes.webapp.date"
                ) as mock_date:
                    mock_date.today.return_value = ref_day
                    mock_dt.now.return_value = ref_now
                    mock_dt.combine = datetime.combine
                    book = await client.post(
                        "/api/webapp/client/booking",
                        json={
                            "slot_id": slot_id,
                            "phone": phone,
                            "service_id": service_id,
                            "first_name": "Клиент",
                        },
                        headers={"X-Telegram-Init-Data": "mock"},
                    )
                assert book.status_code == 200, book.text

    r = await db_session.execute(
        text(
            """
            SELECT e.is_saved, e.is_primary, e.last_booking_service_id
            FROM client_trainer_edges e
            JOIN clients c ON c.id = e.client_id
            WHERE c.telegram_id = :t AND e.trainer_id = :tid
            """
        ),
        {"t": ctg, "tid": trainer_id},
    )
    row = r.fetchone()
    assert row is not None, "booking must create the client-trainer edge"
    assert bool(row[0]) is True, "booked trainer must be saved"
    assert bool(row[1]) is True, "booked trainer must become primary"
    assert int(row[2]) == service_id

    body = await _edges_payload(ctg)
    assert int(body["primary"]["trainer_id"]) == trainer_id
    # Основной тренер не дублируется в «Сохранённых».
    assert trainer_id not in {int(e["trainer_id"]) for e in body.get("saved") or []}
