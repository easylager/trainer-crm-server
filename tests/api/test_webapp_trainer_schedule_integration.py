"""
Integration tests for trainer Mini App schedule API (/api/webapp/schedule/*).

Goals: catch auth/tier mismatches, slot lifecycle bugs, and contract drift — not just HTTP 200.
Requires test DB with subscription_plans seed (alembic upgrade head).
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, time, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app


def _fresh_trainer_telegram_id() -> int:
    return 5_100_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    with patch("src.api.routes.webapp.require_telegram_user_id", return_value=telegram_id):
        yield


async def _grant_crm_subscription(db_session, trainer_id: int) -> None:
    r = await db_session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
    plan_id = r.scalar()
    if plan_id is None:
        pytest.skip("need subscription_plans in DB")
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=400)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES
                (:tid, :pid, 'crm', 1, :st, :exp, 'active')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "st": now, "exp": exp},
    )
    await db_session.commit()


async def _create_active_trainer(db_session, telegram_id: int, *, with_crm: bool = False) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": telegram_id, "id": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Sched', 'Test', 28)"
        ),
        {"tid": trainer_id},
    )
    if with_crm:
        await _grant_crm_subscription(db_session, trainer_id)
    else:
        await db_session.commit()
    return trainer_id


async def _insert_slot(
    db_session,
    trainer_id: int,
    slot_date: date,
    start_h: int,
    end_h: int,
    status: str = "available",
) -> int:
    st = time(start_h, 0)
    en = time(end_h, 0)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :en, :status)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "st": st, "en": en, "status": status},
    )
    sid = r.fetchone()[0]
    await db_session.commit()
    return sid


def _monday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday())


@pytest.mark.asyncio
async def test_schedule_get_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/schedule")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_get_403_when_trainer_not_active(
    app_use_test_db,
    db_session,
) -> None:
    """Schedule uses get_trainer_id_by_telegram_id (active only), unlike profile webapp."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'A', 'B', 30)"
        ),
        {"tid": tid},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/schedule",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 403
    assert "not active" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_schedule_get_returns_slots_in_range_and_shape(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    d0 = date.today() + timedelta(days=3)
    slot_id = await _insert_slot(db_session, trainer_id, d0, 10, 11, "available")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/schedule?from_date={d0.isoformat()}&to_date={d0.isoformat()}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "slots" in data
    assert len(data["slots"]) >= 1
    s0 = next((x for x in data["slots"] if x.get("id") == slot_id), None)
    assert s0 is not None
    assert s0["slot_date"] == d0.isoformat()
    assert s0["start_time"] == "10:00"
    assert s0["end_time"] == "11:00"
    assert s0["status"] == "available"
    assert "booking_id" not in s0


@pytest.mark.asyncio
async def test_schedule_get_init_data_query_param_equivalent_to_header(
    app_use_test_db,
    db_session,
) -> None:
    from urllib.parse import quote

    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=False)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            a = await client.get(
                "/api/webapp/schedule?from_date=2099-01-01&to_date=2099-01-07",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            q = quote("mock", safe="")
            b = await client.get(
                f"/api/webapp/schedule?init_data={q}&from_date=2099-01-01&to_date=2099-01-07",
            )
    assert a.status_code == 200 and b.status_code == 200
    assert a.json() == b.json()


@pytest.mark.asyncio
async def test_schedule_templates_get_empty_then_put_day(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            g0 = await client.get(
                "/api/webapp/schedule/templates",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert g0.status_code == 200
            assert g0.json().get("templates") == []

            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 0,
                    "start_hours": [9, 10, 11],
                    "duration_minutes": 60,
                },
            )
            assert put.status_code == 200
            assert put.json() == {"ok": True}

            g1 = await client.get(
                "/api/webapp/schedule/templates",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    rows = g1.json().get("templates") or []
    assert len(rows) == 3
    hours = sorted(int(x["start_time"].split(":")[0]) for x in rows)
    assert hours == [9, 10, 11]
    assert all(x["day_of_week"] == 0 for x in rows)
    assert all(x["duration_minutes"] == 60 for x in rows)
    assert all("id" in x for x in rows)


@pytest.mark.asyncio
async def test_put_templates_day_403_without_crm_tier(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=False)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"day_of_week": 2, "start_hours": [12], "duration_minutes": 45},
            )
    assert resp.status_code == 403
    assert "CRM" in (resp.json().get("detail") or "")


@pytest.mark.asyncio
async def test_put_templates_day_400_invalid_day_of_week(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"day_of_week": 7, "start_hours": [9], "duration_minutes": 60},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_post_schedule_slots_replaces_day_and_preserves_booked(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    d = date.today() + timedelta(days=5)
    free_id = await _insert_slot(db_session, trainer_id, d, 8, 9, "available")
    booked_id = await _insert_slot(db_session, trainer_id, d, 14, 15, "booked")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"slot_date": d.isoformat(), "start_hours": [10, 11], "duration_minutes": 60},
            )
    assert resp.status_code == 200

    r = await db_session.execute(
        text(
            "SELECT id, start_time, status FROM slots WHERE trainer_id = :tid AND slot_date = :d ORDER BY start_time"
        ),
        {"tid": trainer_id, "d": d},
    )
    rows = r.fetchall()
    times = [(row[1], row[2]) for row in rows]
    assert any(st == time(14, 0) and stt == "booked" for st, stt in times)
    assert any(st == time(10, 0) and stt == "available" for st, stt in times)
    assert not any(row[0] == free_id for row in rows)


@pytest.mark.asyncio
async def test_post_schedule_slots_403_without_crm_tier(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=False)
    d = (date.today() + timedelta(days=4)).isoformat()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"slot_date": d, "start_hours": [9], "duration_minutes": 60},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_apply_week_403_without_crm_tier(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=False)
    mon = _monday_on_or_before(date.today()).isoformat()

    async def _noop_notify(*_a, **_kw):
        return None

    with patch_trainer_webapp_init(tg):
        with patch("src.api.routes.webapp.run_after_schedule_changed", _noop_notify):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/webapp/schedule/apply-week",
                    headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                    json={"week_start": mon},
                )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_schedule_slots_400_bad_date(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"slot_date": "not-a-date", "start_hours": [9], "duration_minutes": 60},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_schedule_slot_404_when_booked(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    d = date.today() + timedelta(days=7)
    sid = await _insert_slot(db_session, trainer_id, d, 16, 17, "booked")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/webapp/schedule/slots/{sid}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404
    assert "booked" in (resp.json().get("detail") or "").lower() or "not found" in (
        resp.json().get("detail") or ""
    ).lower()


@pytest.mark.asyncio
async def test_delete_schedule_slot_200_available(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    d = date.today() + timedelta(days=8)
    sid = await _insert_slot(db_session, trainer_id, d, 12, 13, "available")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/webapp/schedule/slots/{sid}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    r = await db_session.execute(text("SELECT 1 FROM slots WHERE id = :id"), {"id": sid})
    assert r.scalar() is None


@pytest.mark.asyncio
async def test_delete_schedule_slot_404_other_trainers_slot(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    other_tid = await _create_active_trainer(db_session, _fresh_trainer_telegram_id(), with_crm=False)
    d = date.today() + timedelta(days=9)
    sid = await _insert_slot(db_session, other_tid, d, 9, 10, "available")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/webapp/schedule/slots/{sid}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_apply_week_creates_slots_from_template(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    mon = _monday_on_or_before(date.today() + timedelta(days=20))

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"day_of_week": 0, "start_hours": [15], "duration_minutes": 60},
            )
    assert put.status_code == 200

    async def _noop_notify(*_a, **_kw):
        return None

    with patch_trainer_webapp_init(tg):
        with patch("src.api.routes.webapp.run_after_schedule_changed", _noop_notify):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/webapp/schedule/apply-week",
                    headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                    json={"week_start": mon.isoformat()},
                )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert isinstance(body.get("slots_created"), int)
    assert body["slots_created"] >= 1

    r2 = await db_session.execute(
        text(
            """
            SELECT start_time FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            """
        ),
        {"tid": trainer_id, "d": mon},
    )
    starts = [row[0] for row in r2.fetchall()]
    assert any((hasattr(t, "hour") and t.hour == 15) or str(t).startswith("15:") for t in starts)


@pytest.mark.asyncio
async def test_apply_week_400_invalid_week_start(
    app_use_test_db,
    db_session,
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)

    async def _noop_notify(*_a, **_kw):
        return None

    with patch_trainer_webapp_init(tg):
        with patch("src.api.routes.webapp.run_after_schedule_changed", _noop_notify):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/webapp/schedule/apply-week",
                    headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                    json={"week_start": "bad"},
                )
    assert resp.status_code == 400
