"""
TASK-096 S4 — момент первого успеха (AC-004, AC-005).

Что здесь доказывается:
  * ответ на создание записи говорит, первая ли она для этого профиля, и делает это
    по счёту в БД, а не по догадке;
  * план напоминаний в ответе — тот же, что реально запланирован для этой записи;
    поздняя запись без окна до слота напоминаний не обещает (AC-005);
  * повтор запроса с тем же ``Idempotency-Key`` возвращает тот же экран — иначе
    человек, у которого сорвалась сеть, увидел бы «уже не первая» на первой записи;
  * отменённая запись не возвращает статус «первая» второй раз.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.client_first_success import format_reminder_plan_for_client
from tests.api.test_webapp_client_miniapp_integration import (
    _create_trainer_online_with_slot,
    _fresh_client_telegram_id,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _book(client, *, slot_id: int, phone: str, service_id: int, idem: str | None = None):
    headers = {"X-Telegram-Init-Data": "mock"}
    if idem:
        headers["Idempotency-Key"] = idem
    return await client.post(
        "/api/webapp/client/booking",
        json={
            "slot_id": slot_id,
            "phone": phone,
            "service_id": service_id,
            "first_name": "Клиент",
        },
        headers=headers,
    )


def test_reminder_plan_for_client_reads_as_a_phrase() -> None:
    """Клиенту нужен смысл, а не время отправки: у тренера рядом живёт своя формулировка."""
    now = datetime(2026, 9, 9, 12, 0)
    assert (
        format_reminder_plan_for_client([("before_24h", now), ("before_2h", now)])
        == "за сутки и за два часа до начала"
    )
    assert format_reminder_plan_for_client([("before_2h", now)]) == "за два часа до начала"
    assert (
        format_reminder_plan_for_client([("before_evening_prior", now)])
        == "накануне вечером до начала"
    )


def test_empty_reminder_plan_produces_no_promise() -> None:
    """AC-005: нечего обещать — не обещаем. Пустая строка, а не «напомним заранее»."""
    assert format_reminder_plan_for_client([]) == ""
    assert format_reminder_plan_for_client([("unknown_kind", datetime.now())]) == ""


@pytest.mark.asyncio
async def test_first_booking_is_flagged_and_carries_a_real_reminder_plan(
    app_use_test_db, db_session
) -> None:
    """AC-004: первый успех отличается от пятидесятого, и отличие выведено из данных."""
    slot_day = date.today() + timedelta(days=14)
    trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with _client() as client:
            book = await _book(client, slot_id=slot_id, phone=phone, service_id=service_id)

    assert book.status_code == 200, book.text
    body = book.json()
    assert body["is_first_booking"] is True
    # Слот через две недели — оба напоминания помещаются до начала.
    assert body["reminder_plan"] == "за сутки и за два часа до начала"
    del trainer_id


@pytest.mark.asyncio
async def test_second_booking_is_not_first_and_promises_nothing_extra(
    app_use_test_db, db_session
) -> None:
    slot_day = date.today() + timedelta(days=14)
    _t, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18, 20}
    )
    second_slot_id = (
        await db_session.execute(
            text(
                """
                SELECT id FROM slots
                WHERE slot_date = :d AND start_time = :t
                ORDER BY id DESC LIMIT 1
                """
            ),
            {"d": slot_day, "t": time(20, 0)},
        )
    ).scalar_one()

    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with _client() as client:
            first = await _book(client, slot_id=slot_id, phone=phone, service_id=service_id)
            second = await _book(
                client, slot_id=int(second_slot_id), phone=phone, service_id=service_id
            )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["is_first_booking"] is True
    assert second.json()["is_first_booking"] is False
    # Экран второй записи прежний: поля плана напоминаний в нём нет вовсе.
    assert "reminder_plan" not in second.json()


@pytest.mark.asyncio
async def test_idempotent_replay_returns_the_same_first_success_screen(
    app_use_test_db, db_session
) -> None:
    """
    Повтор того же запроса обязан вернуть тот же экран.

    Без этого сорванная сеть на первой записи давала бы человеку экран «обычной»
    записи: запись уже создана, счёт стал равен единице, и наивный пересчёт при
    повторе вернул бы False.
    """
    slot_day = date.today() + timedelta(days=14)
    _t, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )
    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with _client() as client:
            one = await _book(
                client, slot_id=slot_id, phone=phone, service_id=service_id, idem="first-try"
            )
            two = await _book(
                client, slot_id=slot_id, phone=phone, service_id=service_id, idem="first-try"
            )

    assert one.status_code == 200, one.text
    assert two.status_code == 200, two.text
    assert one.json()["booking_id"] == two.json()["booking_id"]
    assert two.json()["is_first_booking"] is True
    assert two.json()["reminder_plan"] == one.json()["reminder_plan"]


@pytest.mark.asyncio
async def test_cancelled_first_booking_does_not_make_the_next_one_first_again(
    app_use_test_db, db_session
) -> None:
    """
    «Первая запись» — про первый раз, а не про первую действующую бронь.

    Иначе человек, отменивший дебютную запись, получил бы поздравление с первой
    записью дважды — и второй раз оно было бы ложью.
    """
    slot_day = date.today() + timedelta(days=14)
    _t, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18, 20}
    )
    second_slot_id = (
        await db_session.execute(
            text(
                "SELECT id FROM slots WHERE slot_date = :d AND start_time = :t ORDER BY id DESC LIMIT 1"
            ),
            {"d": slot_day, "t": time(20, 0)},
        )
    ).scalar_one()

    ctg = _fresh_client_telegram_id()
    phone, _norm = belarus_test_phone(ctg)

    with patch_client_init_auth(ctg):
        async with _client() as client:
            first = await _book(client, slot_id=slot_id, phone=phone, service_id=service_id)
            assert first.status_code == 200, first.text
            await db_session.execute(
                text("UPDATE bookings SET status = 'cancelled' WHERE id = :bid"),
                {"bid": int(first.json()["booking_id"])},
            )
            await db_session.commit()
            second = await _book(
                client, slot_id=int(second_slot_id), phone=phone, service_id=service_id
            )

    assert second.status_code == 200, second.text
    assert second.json()["is_first_booking"] is False
