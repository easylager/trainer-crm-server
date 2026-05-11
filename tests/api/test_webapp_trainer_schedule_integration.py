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
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.shared.webapp_http_messages import TRAINER_WEBAPP_FORBIDDEN_DETAIL


def _fresh_trainer_telegram_id() -> int:
    return 5_100_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
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
    assert resp.json().get("detail") == TRAINER_WEBAPP_FORBIDDEN_DETAIL


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
    assert data.get("trainer_id") == trainer_id
    assert "session_duration_minutes" in data
    assert "schedule_grid" in data
    sg = data["schedule_grid"]
    assert sg.get("kind") == "uniform_step"
    assert sg.get("step_minutes") == 15
    assert sg.get("slot_duration_minutes") is None
    assert int(sg.get("hour_start", -1)) >= 0
    assert len(data["slots"]) >= 1
    s0 = next((x for x in data["slots"] if x.get("id") == slot_id), None)
    assert s0 is not None
    assert s0["slot_date"] == d0.isoformat()
    assert s0["start_time"] == "10:00"
    assert s0["end_time"] == "11:00"
    assert s0["status"] == "available"
    assert "booking_id" not in s0


@pytest.mark.asyncio
async def test_schedule_get_view_list_compact_slots_only(
    app_use_test_db,
    db_session,
) -> None:
    """view=list: read-only Mini App schedule screen — smaller JSON (no grid / profile extras)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    d0 = date.today() + timedelta(days=3)
    slot_id = await _insert_slot(db_session, trainer_id, d0, 10, 11, "available")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/schedule?from_date={d0.isoformat()}&to_date={d0.isoformat()}&view=list",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"slots", "trainer_id"}
    assert data.get("trainer_id") == trainer_id
    assert "schedule_grid" not in data
    assert len(data["slots"]) >= 1
    s0 = next((x for x in data["slots"] if x.get("id") == slot_id), None)
    assert s0 is not None
    assert s0["slot_date"] == d0.isoformat()


@pytest.mark.asyncio
async def test_schedule_get_schedule_grid_zamok_hourly_when_primary(
    app_use_test_db,
    db_session,
) -> None:
    """Primary arena ТЦ Замок → GET /schedule exposes hourly :15 preset (первое начало 10:15, последнее — 22:15)."""
    r = await db_session.execute(text("SELECT id FROM arenas WHERE name = 'ТЦ Замок' LIMIT 1"))
    row = r.fetchone()
    if row is None:
        pytest.skip("need arena ТЦ Замок in DB")
    zamok_id = int(row[0])
    reg = await db_session.execute(text("SELECT to_regclass('public.arena_schedule_presets')"))
    if reg.scalar() is None:
        pytest.skip("need alembic migration 0095 (table arena_schedule_presets)")
    col = await db_session.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'arena_schedule_presets'
              AND column_name = 'slot_duration_minutes'
            """
        )
    )
    if col.fetchone() is None:
        pytest.skip("need alembic migration 0096 (slot_duration_minutes on arena_schedule_presets)")
    pr = await db_session.execute(
        text("SELECT 1 FROM arena_schedule_presets WHERE arena_id = :aid"),
        {"aid": zamok_id},
    )
    if pr.fetchone() is None:
        pytest.skip("need row in arena_schedule_presets for ТЦ Замок (migration 0095 or manual INSERT)")
    await db_session.execute(
        text(
            """
            UPDATE arena_schedule_presets
            SET minute_offset = 15,
                hour_start = 10,
                hour_end = 22,
                slot_duration_minutes = COALESCE(slot_duration_minutes, 45)
            WHERE arena_id = :aid
            """
        ),
        {"aid": zamok_id},
    )
    await db_session.commit()
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": zamok_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": zamok_id, "tid": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/schedule?from_date=2099-01-01&to_date=2099-01-02",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    sg = resp.json().get("schedule_grid") or {}
    assert sg.get("kind") == "hourly_minute"
    assert int(sg.get("minute_offset", -1)) == 15
    assert int(sg.get("hour_start", -1)) == 10
    assert int(sg.get("hour_end", -1)) == 22
    assert sg.get("slot_duration_minutes") == 45


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
async def test_put_templates_day_with_minute_offset(
    app_use_test_db,
    db_session,
) -> None:
    """Template slots can start at non-whole hours (minute field)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 4,
                    "duration_minutes": 90,
                    "slots": [
                        {"hour": 9, "minute": 30, "capacity": 1},
                        {"hour": 11, "minute": 0, "capacity": 1},
                    ],
                },
            )
            assert put.status_code == 200

    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int, EXTRACT(MINUTE FROM start_time)::int, duration_minutes
            FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = 4
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id},
    )
    rows = r.fetchall()
    assert len(rows) == 2
    assert (int(rows[0][0]), int(rows[0][1]), int(rows[0][2])) == (9, 30, 90)
    assert (int(rows[1][0]), int(rows[1][1]), int(rows[1][2])) == (11, 0, 90)


@pytest.mark.asyncio
async def test_post_schedule_slots_with_start_times_strings(
    app_use_test_db,
    db_session,
) -> None:
    """POST /schedule/slots accepts start_times HH:MM (on quarter_15 grid when no arena preset)."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    d = date.today() + timedelta(days=40)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    # 10:10 is not on 15‑minute grid; use 10:15 + 11:45
                    "start_times": ["10:15", "11:45"],
                    "duration_minutes": 70,
                },
            )
    assert resp.status_code == 200
    assert resp.json().get("trainer_id") == trainer_id

    r = await db_session.execute(
        text(
            "SELECT start_time, end_time FROM slots WHERE trainer_id = :tid AND slot_date = :d ORDER BY start_time"
        ),
        {"tid": trainer_id, "d": d},
    )
    rows = r.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == time(10, 15)
    assert rows[1][0] == time(11, 45)


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
            sg0 = g0.json().get("schedule_grid") or {}
            assert sg0.get("kind") == "uniform_step"
            assert sg0.get("step_minutes") == 15
            assert sg0.get("slot_duration_minutes") is None

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
    await db_session.execute(
        text("UPDATE trainer_profiles SET group_classes_enabled = false WHERE trainer_id = :tid"),
        {"tid": trainer_id},
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
async def test_put_templates_day_individual_precise_arena_persists_and_apply_week(
    app_use_test_db,
    db_session,
) -> None:
    """Individual template row may set arena_id (off-grid precise); apply-week creates slot with that arena."""
    r_ids = await db_session.execute(
        text("SELECT id FROM arenas WHERE COALESCE(is_active, true) ORDER BY id LIMIT 2 OFFSET 0"),
    )
    aid_rows = [int(x[0]) for x in r_ids.fetchall()]
    if len(aid_rows) < 2:
        pytest.skip("need 2 arenas in DB for multi-venue template test")
    aid_primary, aid_secondary = aid_rows[0], aid_rows[1]

    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    for aid in (aid_primary, aid_secondary):
        await db_session.execute(
            text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
            {"tid": trainer_id, "aid": aid},
        )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": aid_primary, "tid": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 4,
                    "duration_minutes": 60,
                    "slots": [
                        {"hour": 9, "minute": 0, "capacity": 1},
                        {
                            "hour": 14,
                            "minute": 7,
                            "capacity": 1,
                            "duration_minutes": 45,
                            "arena_id": aid_secondary,
                        },
                    ],
                },
            )
    assert put.status_code == 200, put.text

    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM start_time)::int,
                   EXTRACT(MINUTE FROM start_time)::int,
                   duration_minutes,
                   capacity,
                   arena_id
            FROM trainer_schedule_templates
            WHERE trainer_id = :tid AND day_of_week = 4
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id},
    )
    rows_tpl = r.fetchall()
    assert len(rows_tpl) == 2
    assert int(rows_tpl[0][0]) == 9 and int(rows_tpl[0][1]) == 0 and rows_tpl[0][4] is None
    assert int(rows_tpl[1][0]) == 14 and int(rows_tpl[1][1]) == 7
    assert int(rows_tpl[1][2]) == 45 and int(rows_tpl[1][3]) == 1
    assert int(rows_tpl[1][4]) == aid_secondary

    mon = _monday_on_or_before(date.today() + timedelta(days=30))

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
    slot_d = mon + timedelta(days=4)
    r_slots = await db_session.execute(
        text(
            """
            SELECT arena_id FROM slots
            WHERE trainer_id = :tid AND slot_date = :d
              AND EXTRACT(HOUR FROM start_time)::int = 14
              AND EXTRACT(MINUTE FROM start_time)::int = 7
            """
        ),
        {"tid": trainer_id, "d": slot_d},
    )
    srow = r_slots.fetchone()
    assert srow is not None and int(srow[0]) == aid_secondary


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
async def test_post_schedule_slots_400_when_new_slot_overlaps_existing_kept_slot(
    app_use_test_db,
    db_session,
) -> None:
    """When a selected existing slot stays on day, API must reject overlapping new intervals."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    d = date.today() + timedelta(days=21)
    await _insert_slot(db_session, trainer_id, d, 19, 20, "available")

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "start_times": ["19:00", "19:30"],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 400
    assert "пересека" in (resp.json().get("detail") or "").lower()

    r = await db_session.execute(
        text(
            """
            SELECT start_time, end_time FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status = 'available'
            ORDER BY start_time
            """
        ),
        {"tid": trainer_id, "d": d},
    )
    rows = r.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == time(19, 0)
    assert rows[0][1] == time(20, 0)


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

    # Precondition: groups off in profile (DB default is now true — must be explicit in test).
    await db_session.execute(
        text("UPDATE trainer_profiles SET group_classes_enabled = false WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()

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
    assert body.get("trainer_id") == trainer_id

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
async def test_apply_week_does_not_duplicate_booked_slot_same_interval(
    app_use_test_db,
    db_session,
) -> None:
    """Applying template must not INSERT a free slot on top of an existing booked interval."""
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
    r_client = await db_session.execute(
        text(
            "INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'Клиент') RETURNING id"
        ),
        {"tg": _fresh_trainer_telegram_id()},
    )
    client_id = r_client.fetchone()[0]
    mon = _monday_on_or_before(date.today() + timedelta(days=30))
    sun = mon + timedelta(days=6)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, TIME '17:15', TIME '18:00', 'booked', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": sun},
    )
    slot_id = r_slot.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": svc_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            put = await client.put(
                "/api/webapp/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "day_of_week": 6,
                    "duration_minutes": 45,
                    "slots": [{"hour": 17, "minute": 15, "capacity": 1}],
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

    r_cnt = await db_session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM slots
            WHERE trainer_id = :tid AND slot_date = :d AND status != 'cancelled'
              AND start_time < TIME '18:00' AND end_time > TIME '17:15'
            """
        ),
        {"tid": trainer_id, "d": sun},
    )
    assert int(r_cnt.scalar() or 0) == 1


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


@pytest.mark.asyncio
async def test_trainer_booking_quick_creates_slot_and_booking(
    app_use_test_db,
    db_session,
) -> None:
    """POST /trainer/booking/quick creates individual slot + booking when CRM active."""
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=10)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Quick', 'Book', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/booking/quick",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": d0.isoformat(),
                    "start_hour": 14,
                    "duration_minutes": 60,
                    "client_id": client_id,
                    "service_id": service_id,
                },
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    booking_id = data.get("booking_id")
    slot_id = data.get("slot_id")
    assert booking_id and slot_id

    r2 = await db_session.execute(
        text("SELECT slot_id FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row = r2.fetchone()
    assert row is not None
    assert int(row[0]) == int(slot_id)


@pytest.mark.asyncio
async def test_trainer_booking_quick_400_when_time_occupied(
    app_use_test_db,
    db_session,
) -> None:
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=11)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    slot_id = await _insert_slot(db_session, trainer_id, d0, 15, 16, "available")
    ctg_a = unique_test_telegram_id()
    phone_a, phone_n_a = belarus_test_phone(ctg_a)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'A', 'One', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg_a, "phone": phone_a, "pn": phone_n_a},
    )
    (client_a,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_a, "svc": service_id},
    )
    ctg_b = unique_test_telegram_id()
    phone_b, phone_n_b = belarus_test_phone(ctg_b)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'B', 'Two', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg_b, "phone": phone_b, "pn": phone_n_b},
    )
    (client_b,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/booking/quick",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": d0.isoformat(),
                    "start_hour": 15,
                    "duration_minutes": 60,
                    "client_id": client_b,
                    "service_id": service_id,
                },
            )
    assert resp.status_code == 400
    assert "занят" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_trainer_booking_quick_400_overlap_empty_slot(
    app_use_test_db,
    db_session,
) -> None:
    """Quick book interval must not overlap an existing slot (15:15 vs 15:00–16:00)."""
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=14)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    await _insert_slot(db_session, trainer_id, d0, 15, 16, "available")
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'O', 'vl', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/booking/quick",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": d0.isoformat(),
                    "start_time": "15:15",
                    "duration_minutes": 60,
                    "client_id": client_id,
                    "service_id": service_id,
                },
            )
    assert resp.status_code == 400
    assert "пересека" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_trainer_booking_quick_400_group_slot_at_hour(
    app_use_test_db,
    db_session,
) -> None:
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=12)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :et, 'available', 2, :svc)
            """
        ),
        {
            "tid": trainer_id,
            "d": d0,
            "st": time(16, 0),
            "et": time(17, 0),
            "svc": service_id,
        },
    )
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'G', 'rp', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/booking/quick",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": d0.isoformat(),
                    "start_hour": 16,
                    "duration_minutes": 60,
                    "client_id": client_id,
                    "service_id": service_id,
                },
            )
    assert resp.status_code == 400
    assert "группов" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_trainer_booking_quick_403_without_crm(
    app_use_test_db,
    db_session,
) -> None:
    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id

    d0 = date.today() + timedelta(days=13)
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_id, "tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_id, "tid": trainer_id},
    )
    ctg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(ctg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'No', 'Crm', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": ctg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/booking/quick",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "slot_date": d0.isoformat(),
                    "start_hour": 11,
                    "duration_minutes": 60,
                    "client_id": client_id,
                    "service_id": service_id,
                },
            )
    assert resp.status_code == 403
