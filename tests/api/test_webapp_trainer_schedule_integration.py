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
from unittest.mock import MagicMock, patch

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
    *,
    capacity: int = 1,
    service_id: int | None = None,
) -> int:
    st = time(start_h, 0)
    en = time(end_h, 0)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :en, :status, :cap, :svc)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": st,
            "en": en,
            "status": status,
            "cap": capacity,
            "svc": service_id,
        },
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
async def test_schedule_get_group_slot_includes_bookings_array(
    app_use_test_db,
    db_session,
) -> None:
    """GET /schedule returns bookings[] for group slots (capacity>1, multiple active bookings)."""
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=5)
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Group', 'Trainer', 28, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :et, 'booked', 2, :svc)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": d0, "st": time(10, 0), "et": time(11, 0), "svc": service_id},
    )
    (slot_id,) = r.fetchone()
    booking_ids: list[int] = []
    for first, last in (("Ann", "One"), ("Bob", "Two")):
        ctg = unique_test_telegram_id()
        phone, phone_n = belarus_test_phone(ctg)
        r = await db_session.execute(
            text(
                """
                INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
                VALUES (:tg, :fn, :ln, :phone, :pn)
                RETURNING id
                """
            ),
            {"tg": ctg, "fn": first, "ln": last, "phone": phone, "pn": phone_n},
        )
        (client_id,) = r.fetchone()
        r = await db_session.execute(
            text(
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
                VALUES (:sid, :tid, :cid, :svc, 'confirmed')
                RETURNING id
                """
            ),
            {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
        )
        booking_ids.append(int(r.fetchone()[0]))
    await db_session.commit()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/schedule?from_date={d0.isoformat()}&to_date={d0.isoformat()}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    s0 = next((x for x in resp.json()["slots"] if x.get("id") == slot_id), None)
    assert s0 is not None
    assert s0.get("capacity") == 2
    assert s0.get("active_bookings") == 2
    bs = s0.get("bookings")
    assert isinstance(bs, list) and len(bs) == 2
    assert sorted(b["booking_id"] for b in bs) == sorted(booking_ids)
    previews = {b["client_preview"] for b in bs}
    assert "Ann One" in previews and "Bob Two" in previews


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
    assert all(int(x.get("capacity", 1)) == 1 for x in rows)
    assert all("id" in x for x in rows)


@pytest.mark.asyncio
async def test_put_templates_day_mixed_capacity_and_apply_week(
    app_use_test_db,
    db_session,
) -> None:
    """Template is individual-only (capacity 1); apply-week creates matching slots."""
    from tests.db_catalog_helpers import require_seed_service_id

    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET group_classes_enabled = true WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    svc_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": svc_id},
    )
    await db_session.commit()
    mon = _monday_on_or_before(date.today() + timedelta(days=25))

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 1,
                    "duration_minutes": 60,
                    "slots": [
                        {"hour": 10, "capacity": 1},
                        {"hour": 11, "capacity": 1, "service_id": svc_id},
                    ],
                },
            )
            assert put.status_code == 200

    async def _noop_notify(*_a, **_kw):
        return None

    with patch_trainer_webapp_init(tg):
        with patch("src.api.routes.webapp.run_after_schedule_changed", _noop_notify):
            with patch("src.api.routes.webapp.Bot", return_value=MagicMock()):
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    resp = await client.post(
                        "/api/webapp/schedule/apply-week",
                        headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                        json={"week_start": mon.isoformat()},
                    )
    assert resp.status_code == 200
    slot_date = mon + timedelta(days=1)
    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int, capacity FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id, "d": slot_date},
    )
    by_h = {int(row[0]): int(row[1]) for row in r.fetchall()}
    assert by_h.get(10) == 1
    assert by_h.get(11) == 1


@pytest.mark.asyncio
async def test_put_templates_day_400_group_when_profile_disabled(
    app_use_test_db,
    db_session,
) -> None:
    """Capacity > 1 in template requires group_classes_enabled in profile."""
    from tests.db_catalog_helpers import require_seed_service_id

    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    svc_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": svc_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 2,
                    "duration_minutes": 60,
                    "slots": [{"hour": 9, "capacity": 4, "service_id": svc_id}],
                },
            )
    assert resp.status_code == 400
    assert "профиле" in (resp.json().get("detail") or "")


@pytest.mark.asyncio
async def test_put_templates_day_200_group_capacity_when_enabled(
    app_use_test_db,
    db_session,
) -> None:
    """Group template slots (capacity > 1) are saved when profile allows group classes."""
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET group_classes_enabled = true WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    svc_id = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": svc_id},
    )
    aid, _city_id, _ = await require_seed_arena_city_name(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": aid},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 3,
                    "duration_minutes": 60,
                    "slots": [{"hour": 9, "capacity": 4, "service_id": svc_id}],
                },
            )
    assert resp.status_code == 200

    r = await db_session.execute(
        text(
            """
            SELECT capacity, service_id, arena_id FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = 3 AND EXTRACT(HOUR FROM start_time)::int = 9
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    assert row is not None
    assert int(row[0]) == 4
    assert int(row[1]) == svc_id
    assert int(row[2]) == aid


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
async def test_post_schedule_slots_200_group_slots_when_profile_enabled(
    app_use_test_db,
    db_session,
) -> None:
    """POST creates group slots (capacity > 1) when profile has group classes enabled."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET group_classes_enabled = true WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    from tests.db_catalog_helpers import require_seed_service_id

    group_svc = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": group_svc},
    )
    await db_session.commit()

    # No pre-existing slots: replace_slots_for_day only sets capacity on newly inserted hours.
    d = date.today() + timedelta(days=60)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "start_hours": [10, 11, 12],
                    "duration_minutes": 60,
                    "capacity": 5,
                    "group_service_id": group_svc,
                },
            )
    assert resp.status_code == 200

    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int, capacity, service_id
            FROM slots WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id, "d": d},
    )
    by_h = {int(row[0]): (int(row[1]), int(row[2]) if row[2] is not None else None) for row in r.fetchall()}
    for h in (10, 11, 12):
        assert by_h[h][0] == 5
        assert by_h[h][1] == group_svc


@pytest.mark.asyncio
async def test_post_schedule_slots_400_group_when_profile_disabled_leaves_db_unchanged(
    app_use_test_db,
    db_session,
) -> None:
    """POST with capacity > 1 returns 400 when group_classes_enabled is off; DB unchanged."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    from tests.db_catalog_helpers import require_seed_service_id

    group_svc = await require_seed_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": group_svc},
    )
    await db_session.commit()

    d = date.today() + timedelta(days=11)
    await _insert_slot(db_session, trainer_id, d, 10, 11, "available", capacity=1)
    await _insert_slot(db_session, trainer_id, d, 11, 12, "available", capacity=1)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "start_hours": [10, 11],
                    "duration_minutes": 60,
                    "capacity": 7,
                    "group_service_id": group_svc,
                },
            )
    assert resp.status_code == 400
    assert "профиле" in (resp.json().get("detail") or "")

    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int, capacity
            FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id, "d": d},
    )
    by_hour = {int(row[0]): int(row[1]) for row in r.fetchall()}
    assert by_hour.get(10) == 1
    assert by_hour.get(11) == 1


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

    # Bot(...) validates token at import time; CI has no real TELEGRAM_BOT_TOKEN_TRAINER.
    with patch_trainer_webapp_init(tg):
        with patch("src.api.routes.webapp.run_after_schedule_changed", _noop_notify):
            with patch("src.api.routes.webapp.Bot", return_value=MagicMock()):
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


@pytest.mark.asyncio
async def test_trainer_booking_detail_includes_client_id(
    app_use_test_db,
    db_session,
) -> None:
    """GET /trainer/bookings/{id} exposes client_id for Mini App profile deep link."""
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    tomorrow = date.today() + timedelta(days=1)
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Test', 'Trainer', 25, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json().get("client_id") == client_id


@pytest.mark.asyncio
async def test_schedule_and_booking_detail_include_completed_past_booking(
    app_use_test_db,
    db_session,
) -> None:
    """Completed bookings attach to /schedule and open via GET /trainer/bookings/{id} (history week)."""
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    past_day = date.today() - timedelta(days=10)
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tg, "id": trainer_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'Past', 'Trainer', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": past_day, "st": time(14, 0), "et": time(15, 0)},
    )
    (slot_id,) = r.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Done', 'Client', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    d_from = _monday_on_or_before(past_day)
    d_to = d_from + timedelta(days=6)

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            sched = await client.get(
                f"/api/webapp/schedule?from_date={d_from.isoformat()}&to_date={d_to.isoformat()}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            detail = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )

    assert sched.status_code == 200
    slots = sched.json().get("slots") or []
    match = next((x for x in slots if x.get("id") == slot_id), None)
    assert match is not None
    assert match.get("status") == "booked"
    assert match.get("booking_id") == booking_id
    assert match.get("booking_status") == "completed"

    assert detail.status_code == 200
    body = detail.json()
    assert body.get("id") == booking_id
    assert body.get("status") == "completed"
    assert body.get("client_id") == client_id
