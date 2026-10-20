"""
«Первые три ученика» (TASK-310): GET/POST /api/webapp/trainer/first-students.

Продуктовое обещание: тренер с собранной неделей одним листом переносит своего ученика —
имени достаточно — и тот сразу стоит в окне его же недели. Ученик остаётся в CRM, даже если
окно успели занять, а «каждую неделю» ставит закрепление теми же правилами, что и расписание.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.trainer_first_students import initials, local_today, slot_label
from tests.db_catalog_helpers import require_seed_service_id

URL = "/api/webapp/trainer/first-students"
HDR = {"X-Telegram-Init-Data": "mock"}


def _tg() -> int:
    return 5_430_000_000 + (uuid.uuid4().int % 4_000_000_000)


@pytest.fixture(autouse=True)
def _no_telegram_pushes() -> Iterator[None]:
    """Запись шлёт пуши через aiogram Bot — в CI токены фиктивные, и Bot падает ещё при создании."""
    from unittest.mock import AsyncMock

    with patch("src.api.routes.webapp._notify_client_trainer_booked_after_create", new=AsyncMock()), patch(
        "src.api.routes.webapp._send_trainer_post_booking_feedback", new=AsyncMock()
    ):
        yield


@contextmanager
def _as_trainer(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _trainer_with_week(db_session, telegram_id: int) -> tuple[int, int]:
    """Неделя собрана, услуга есть, клиентов нет — ровно те 12 тренеров из воронки."""
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id"))
    trainer_id = int(r.scalar_one())
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"), {"tg": telegram_id, "id": trainer_id}
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, onboarding_completed_at) "
            "VALUES (:tid, 'Тренер', now())"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
    plan_id = r.scalar()
    if plan_id is None:
        pytest.skip("need subscription_plans in DB")
    now = datetime.now(timezone.utc)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES (:tid, :pid, 'crm', 1, :st, :exp, 'active')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "st": now, "exp": now + timedelta(days=400)},
    )
    await db_session.commit()
    return trainer_id, service_id


async def _slot(db_session, trainer_id: int, day: date, start: time, status: str = "available") -> int:
    end = time(start.hour + 1, start.minute)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :en, :status, 1) RETURNING id
            """
        ),
        {"tid": trainer_id, "d": day, "st": start, "en": end, "status": status},
    )
    await db_session.commit()
    return int(r.scalar_one())


def test_slot_label_reads_like_a_person_says_it() -> None:
    mon = date(2026, 10, 19)
    assert slot_label(mon, time(18, 0), today=mon) == "сегодня 18:00"
    assert slot_label(mon + timedelta(days=1), time(9, 30), today=mon) == "завтра 9:30"
    assert slot_label(mon + timedelta(days=3), time(17, 0), today=mon) == "чт 17:00"
    assert slot_label(mon + timedelta(days=7), time(17, 0), today=mon) == "пн 26.10 17:00"


def test_initials() -> None:
    assert initials("Маша", "Ковалёва") == "МК"
    assert initials("даня", None) == "Д"
    assert initials("", "") == "?"


@pytest.mark.asyncio
async def test_state_offers_only_future_free_windows(app_use_test_db, db_session) -> None:
    tg = _tg()
    trainer_id, _ = await _trainer_with_week(db_session, tg)
    today = local_today()
    free = await _slot(db_session, trainer_id, today + timedelta(days=2), time(18, 0))
    await _slot(db_session, trainer_id, today + timedelta(days=3), time(18, 0), status="booked")
    await _slot(db_session, trainer_id, today - timedelta(days=1), time(18, 0))
    await _slot(db_session, trainer_id, today + timedelta(days=30), time(18, 0))

    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get(URL, headers=HDR)
    assert res.status_code == 200
    body = res.json()
    assert body["goal"] == 3
    assert body["count"] == 0
    assert body["students"] == []
    assert [o["slot_id"] for o in body["options"]] == [free]


@pytest.mark.asyncio
async def test_name_only_student_lands_in_the_window(app_use_test_db, db_session) -> None:
    tg = _tg()
    trainer_id, _ = await _trainer_with_week(db_session, tg)
    day = local_today() + timedelta(days=2)
    slot_id = await _slot(db_session, trainer_id, day, time(18, 0))

    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(URL, headers=HDR, json={"first_name": " Маша ", "slot_id": slot_id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["warning"] is None
    assert body["booking_id"] is not None
    assert body["booked_label"] == slot_label(day, time(18, 0), today=local_today())

    row = (
        await db_session.execute(
            text("SELECT first_name, phone, telegram_id FROM clients WHERE id = :cid"),
            {"cid": body["client_id"]},
        )
    ).one()
    assert row == ("Маша", None, None)
    status = (
        await db_session.execute(text("SELECT status FROM bookings WHERE id = :bid"), {"bid": body["booking_id"]})
    ).scalar_one()
    assert status in ("confirmed", "pending")

    state = body["state"]
    assert state["count"] == 1
    assert state["students"][0]["name"] == "Маша"
    assert state["students"][0]["has_bot"] is False
    assert state["students"][0]["next_label"] == body["booked_label"]
    assert slot_id not in [o["slot_id"] for o in state["options"]]


@pytest.mark.asyncio
async def test_weekly_pins_the_same_hour_next_week(app_use_test_db, db_session) -> None:
    tg = _tg()
    trainer_id, _ = await _trainer_with_week(db_session, tg)
    day = local_today() + timedelta(days=1)
    slot_id = await _slot(db_session, trainer_id, day, time(17, 0))
    next_week = await _slot(db_session, trainer_id, day + timedelta(days=7), time(17, 0))

    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                URL, headers=HDR, json={"first_name": "Даня", "slot_id": slot_id, "weekly": True}
            )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["weekly"] is True, body["warning"]
    rules = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM recurring_client_slots WHERE trainer_id = :tid AND client_id = :cid"),
            {"tid": trainer_id, "cid": body["client_id"]},
        )
    ).scalar_one()
    assert rules == 1
    booked_next = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM bookings WHERE slot_id = :sid AND client_id = :cid "
                "AND status NOT IN ('cancelled', 'declined')"
            ),
            {"sid": next_week, "cid": body["client_id"]},
        )
    ).scalar_one()
    assert booked_next == 1


@pytest.mark.asyncio
async def test_taken_window_keeps_the_student(app_use_test_db, db_session) -> None:
    tg = _tg()
    trainer_id, _ = await _trainer_with_week(db_session, tg)
    slot_id = await _slot(db_session, trainer_id, local_today() + timedelta(days=2), time(18, 0), status="booked")

    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(URL, headers=HDR, json={"first_name": "Лиза", "slot_id": slot_id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["booking_id"] is None
    assert body["warning"] and body["warning"].startswith("Ученик добавлен")
    assert body["state"]["count"] == 1


@pytest.mark.asyncio
async def test_phone_is_optional_but_validated(app_use_test_db, db_session) -> None:
    tg = _tg()
    await _trainer_with_week(db_session, tg)
    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            bad = await client.post(URL, headers=HDR, json={"first_name": "Оля", "phone": "12"})
            ok = await client.post(
                URL, headers=HDR, json={"first_name": "Оля", "phone": f"+37529{uuid.uuid4().int % 10**7:07d}"}
            )
    assert bad.status_code == 422
    assert ok.status_code == 200, ok.text
    assert ok.json()["booking_id"] is None
    assert ok.json()["state"]["count"] == 1


@pytest.mark.asyncio
async def test_other_trainers_window_is_refused(app_use_test_db, db_session) -> None:
    tg, other_tg = _tg(), _tg()
    await _trainer_with_week(db_session, tg)
    other_id, _ = await _trainer_with_week(db_session, other_tg)
    foreign = await _slot(db_session, other_id, local_today() + timedelta(days=2), time(18, 0))
    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(URL, headers=HDR, json={"first_name": "Чужой", "slot_id": foreign})
    assert res.status_code == 200
    assert res.json()["booking_id"] is None
    status = (await db_session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": foreign})).scalar_one()
    assert status == "available"


@pytest.mark.asyncio
async def test_chosen_service_is_booked_and_foreign_one_refused(app_use_test_db, db_session) -> None:
    """Две услуги в онбординге — запись идёт на выбранную, а не молча на первую."""
    tg = _tg()
    trainer_id, first_service = await _trainer_with_week(db_session, tg)
    other = (
        await db_session.execute(
            text("SELECT id FROM services WHERE id <> :sid ORDER BY sort_order, id LIMIT 1"), {"sid": first_service}
        )
    ).scalar()
    if other is None:
        pytest.skip("need two services in DB")
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 6000)"),
        {"tid": trainer_id, "sid": other},
    )
    await db_session.commit()
    slot_id = await _slot(db_session, trainer_id, local_today() + timedelta(days=2), time(18, 0))
    stranger = (
        await db_session.execute(
            text("SELECT id FROM services WHERE id NOT IN (:a, :b) ORDER BY id LIMIT 1"), {"a": first_service, "b": other}
        )
    ).scalar()

    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            state = (await client.get(URL, headers=HDR)).json()
            res = await client.post(
                URL, headers=HDR, json={"first_name": "Маша", "slot_id": slot_id, "service_id": other}
            )
            refused = (
                await client.post(URL, headers=HDR, json={"first_name": "Чужая", "slot_id": slot_id, "service_id": stranger})
                if stranger is not None
                else None
            )
    assert {s["service_id"] for s in state["services"]} == {first_service, other}
    assert state["can_book"] is True
    assert res.status_code == 200, res.text
    booked_service = (
        await db_session.execute(text("SELECT service_id FROM bookings WHERE id = :bid"), {"bid": res.json()["booking_id"]})
    ).scalar_one()
    assert booked_service == other
    if refused is not None:
        assert refused.status_code == 400


@pytest.mark.asyncio
async def test_without_crm_no_windows_are_offered(app_use_test_db, db_session) -> None:
    """Подписка кончилась — запись не создать, поэтому лист не предлагает окна, но ученика добавить можно."""
    tg = _tg()
    trainer_id, _ = await _trainer_with_week(db_session, tg)
    await db_session.execute(
        text("UPDATE trainer_subscriptions SET expires_at = now() - interval '1 day', status = 'expired' WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()
    await _slot(db_session, trainer_id, local_today() + timedelta(days=2), time(18, 0))
    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            state = (await client.get(URL, headers=HDR)).json()
            res = await client.post(URL, headers=HDR, json={"first_name": "Оля"})
    assert state["can_book"] is False
    assert state["options"] == []
    assert res.status_code == 200
    assert res.json()["state"]["count"] == 1


@pytest.mark.asyncio
async def test_weekly_keeps_the_chosen_service_every_week(app_use_test_db, db_session) -> None:
    """Правило «каждую неделю» не хранит услугу — автозаписи раньше уходили на первую услугу тренера."""
    tg = _tg()
    trainer_id, first_service = await _trainer_with_week(db_session, tg)
    other = (
        await db_session.execute(
            text("SELECT id FROM services WHERE id <> :sid ORDER BY sort_order, id LIMIT 1"), {"sid": first_service}
        )
    ).scalar()
    if other is None:
        pytest.skip("need two services in DB")
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 6000)"),
        {"tid": trainer_id, "sid": other},
    )
    await db_session.commit()
    day = local_today() + timedelta(days=1)
    slot_id = await _slot(db_session, trainer_id, day, time(17, 0))
    await _slot(db_session, trainer_id, day + timedelta(days=7), time(17, 0))
    with _as_trainer(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                URL,
                headers=HDR,
                json={"first_name": "Маша", "slot_id": slot_id, "service_id": other, "weekly": True},
            )
    assert res.status_code == 200, res.text
    assert res.json()["weekly"] is True, res.json()["warning"]
    services = (
        await db_session.execute(
            text(
                "SELECT DISTINCT service_id FROM bookings WHERE trainer_id = :tid AND client_id = :cid "
                "AND status NOT IN ('cancelled', 'declined')"
            ),
            {"tid": trainer_id, "cid": res.json()["client_id"]},
        )
    ).scalars().all()
    assert services == [other]
