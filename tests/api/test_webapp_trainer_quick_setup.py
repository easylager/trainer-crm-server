"""
Onboarding v2 first run: GET/POST /api/webapp/trainer/onboarding/quick-setup.

The contract under test is the product promise, not the HTTP shape: a trainer who linked their
Telegram seconds ago and has filled in nothing must be able to go from zero to a bookable week
in one request, without a profile, a photo, a city, an arena or moderation.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.shared.webapp_http_messages import TRAINER_WEBAPP_FORBIDDEN_DETAIL

QUICK_SETUP_URL = "/api/webapp/trainer/onboarding/quick-setup"


def _fresh_trainer_telegram_id() -> int:
    return 5_400_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _grant_crm(db_session, trainer_id: int) -> None:
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


async def _bare_linked_trainer(db_session, telegram_id: int) -> int:
    """A trainer row and a Telegram id. Nothing else — exactly what /start produces."""
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": telegram_id, "id": trainer_id},
    )
    await db_session.commit()
    await _grant_crm(db_session, trainer_id)
    return trainer_id


async def _any_service_id(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("need services in DB")
    return int(row[0])


@pytest.mark.asyncio
async def test_get_offers_a_prefilled_week_not_an_empty_form(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _bare_linked_trainer(db_session, tg)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["week_is_suggestion"] is True
    assert data["already_done"] is False
    assert data["week"], "first run must arrive pre-filled — an empty grid is a form"
    assert all(d["hours"] for d in data["week"])
    assert data["services"], "the trainer must have something to tap"


@pytest.mark.asyncio
async def test_bare_trainer_gets_a_bookable_week_in_one_call(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": d, "hours": [7, 18, 19]} for d in range(5)],
                    "duration_minutes": 60,
                },
            )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["days_with_slots"] == 5
    assert data["slots_created"] > 0

    r = await db_session.execute(
        text("SELECT COUNT(*) FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == 15, "5 days x 3 hours"

    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE trainer_id = :t AND status = 'available'"),
        {"t": trainer_id},
    )
    assert r.scalar() > 0

    r = await db_session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert [int(x[0]) for x in r.fetchall()] == [service_id]


@pytest.mark.asyncio
async def test_defaults_are_applied_without_asking(app_use_test_db, db_session) -> None:
    """Session length and booking window are product decisions, not first-run questions."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 2, "hours": [10]}],
                    "duration_minutes": 60,
                },
            )

    r = await db_session.execute(
        text(
            "SELECT session_duration_minutes, min_hours_before_booking "
            "FROM trainer_profiles WHERE trainer_id = :t"
        ),
        {"t": trainer_id},
    )
    row = r.fetchone()
    assert row is not None, "quick setup must create the profile row it needs"
    assert row[0] == 60
    assert row[1] is not None


@pytest.mark.asyncio
async def test_booking_window_is_never_overwritten(app_use_test_db, db_session) -> None:
    """
    Разделение осознанное: окно записи мы не спрашивали — значит не трогаем.
    Длительность занятия спрашивали — значит пишем то, что выбрано (см. следующий тест).
    """
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, session_duration_minutes, min_hours_before_booking) "
            "VALUES (:t, 90, 48)"
        ),
        {"t": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Экран заранее показывает текущую длительность тренера, поэтому «повторное
            # открытие без изменений» отправляет именно её.
            get_resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})
            assert get_resp.json()["duration_minutes"] == 90, "экран должен открыться с текущим значением"
            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 1, "hours": [11]}],
                    "duration_minutes": 90,
                },
            )

    r = await db_session.execute(
        text(
            "SELECT session_duration_minutes, min_hours_before_booking "
            "FROM trainer_profiles WHERE trainer_id = :t"
        ),
        {"t": trainer_id},
    )
    assert r.fetchone() == (90, 48)


@pytest.mark.asyncio
async def test_second_run_reports_already_done_and_echoes_the_saved_week(
    app_use_test_db, db_session
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 3, "hours": [6, 21]}],
                    "duration_minutes": 60,
                },
            )
            resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})

    data = resp.json()
    assert data["already_done"] is True
    assert data["week_is_suggestion"] is False
    assert data["week"] == [{"day_of_week": 3, "hours": [6, 21], "arena_id": None}]
    assert data["selected_service_ids"] == [service_id]


@pytest.mark.asyncio
async def test_unchecking_a_day_clears_it(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for days in ([{"day_of_week": 0, "hours": [8]}, {"day_of_week": 1, "hours": [8]}],
                         [{"day_of_week": 0, "hours": [8]}]):
                await client.post(
                    QUICK_SETUP_URL,
                    headers={"X-Telegram-Init-Data": "mock"},
                    json={"service_ids": [service_id], "days": days, "duration_minutes": 60},
                )

    r = await db_session.execute(
        text("SELECT day_of_week FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert [int(x[0]) for x in r.fetchall()] == [0]


@pytest.mark.asyncio
async def test_empty_week_is_rejected_with_a_human_reason(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={"service_ids": [service_id], "days": [], "duration_minutes": 60},
            )

    assert resp.status_code == 400
    assert "ученику" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_deactivated_trainer_is_refused(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('deactivated') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})

    assert resp.status_code == 403
    assert resp.json()["detail"] == TRAINER_WEBAPP_FORBIDDEN_DETAIL


@pytest.mark.asyncio
async def test_rerun_keeps_an_existing_booking(app_use_test_db, db_session) -> None:
    """
    The dangerous case: trainer edits the week after a client already booked.
    Re-running quick setup must not delete a booked slot.
    """
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": d, "hours": [9]} for d in range(7)],
                    "duration_minutes": 60,
                },
            )

            r = await db_session.execute(
                text(
                    "SELECT id FROM slots WHERE trainer_id = :t AND slot_date > :d "
                    "ORDER BY slot_date LIMIT 1"
                ),
                {"t": trainer_id, "d": date.today()},
            )
            slot_id = int(r.fetchone()[0])
            rc = await db_session.execute(
                text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'Max') RETURNING id"),
                {"tg": _fresh_trainer_telegram_id()},
            )
            client_id = int(rc.fetchone()[0])
            await db_session.execute(
                text(
                    "INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status) "
                    "VALUES (:t, :c, :s, :svc, 'confirmed')"
                ),
                {"t": trainer_id, "c": client_id, "s": slot_id, "svc": service_id},
            )
            await db_session.execute(
                text("UPDATE slots SET status = 'booked' WHERE id = :s"), {"s": slot_id}
            )
            await db_session.commit()

            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 5, "hours": [15]}],
                    "duration_minutes": 60,
                },
            )

    r = await db_session.execute(text("SELECT status FROM slots WHERE id = :s"), {"s": slot_id})
    row = r.fetchone()
    assert row is not None, "a booked slot must survive a schedule rewrite"
    assert row[0] == "booked"


@pytest.mark.asyncio
async def test_chosen_duration_wins_over_the_column_default(app_use_test_db, db_session) -> None:
    """
    Регрессия: колонка session_duration_minutes имеет DB-дефолт 45, поэтому она никогда не NULL,
    и COALESCE оставлял 45, пока в расписании создавались 60-минутные слоты. Профиль и расписание
    расходились молча — тренер узнавал об этом только когда клиент записывался не на то время.
    """
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_profiles (trainer_id, first_name) VALUES (:t, 'Пред')"),
        {"t": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 2, "hours": [10]}],
                    "duration_minutes": 90,
                },
            )
    assert resp.status_code == 200, resp.text

    r = await db_session.execute(
        text("SELECT session_duration_minutes FROM trainer_profiles WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == 90

    r = await db_session.execute(
        text("SELECT DISTINCT duration_minutes FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert [int(x[0]) for x in r.fetchall()] == [90], "профиль и расписание должны говорить одно и то же"


async def _fresh_city_and_arenas(db_session) -> tuple[int, int, int]:
    """Two arenas in one city; the first has ТЦ Замок's real preset (:15 offset, fixed)."""
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if row:
        city_id = int(row[0])
    else:
        r = await db_session.execute(text("INSERT INTO cities (name) VALUES ('Т') RETURNING id"))
        city_id = int(r.fetchone()[0])

    r = await db_session.execute(
        text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, 'ТЦ Замок HTTP', true) RETURNING id"),
        {"c": city_id},
    )
    zamok = int(r.fetchone()[0])
    await db_session.execute(
        text(
            "INSERT INTO arena_schedule_presets (arena_id, grid_kind, minute_offset, hour_start, hour_end) "
            "VALUES (:a, 'hourly_minute', 15, 10, 22)"
        ),
        {"a": zamok},
    )
    r = await db_session.execute(
        text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, 'Манеж HTTP', true) RETURNING id"),
        {"c": city_id},
    )
    manege = int(r.fetchone()[0])
    await db_session.commit()
    return city_id, zamok, manege


@pytest.mark.asyncio
async def test_get_lists_arenas_with_their_real_grid(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _bare_linked_trainer(db_session, tg)
    _city_id, zamok, _manege = await _fresh_city_and_arenas(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})

    data = resp.json()
    zamok_row = next(a for a in data["arenas"] if a["id"] == zamok)
    assert zamok_row["grid_kind"] == "hourly_minute"
    assert zamok_row["minute_offset"] == 15
    assert zamok_row["hour_start"] == 10
    assert zamok_row["hour_end"] == 22
    assert data["linked_arena_ids"] == []
    assert data["multi_arena"] is False


@pytest.mark.asyncio
async def test_post_with_a_single_arena_shifts_slots_and_links_it(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)
    _city_id, zamok, _manege = await _fresh_city_and_arenas(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [{"day_of_week": 0, "hours": [11], "arena_id": zamok}],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 200, resp.text

    r = await db_session.execute(
        text("SELECT start_time, arena_id FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    row = r.fetchone()
    assert str(row[0]) == "11:15:00"
    assert int(row[1]) == zamok

    r = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :t"), {"t": trainer_id}
    )
    assert r.scalar() == zamok


@pytest.mark.asyncio
async def test_get_after_multi_arena_post_reports_multi_arena_true(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _bare_linked_trainer(db_session, tg)
    service_id = await _any_service_id(db_session)
    _city_id, zamok, manege = await _fresh_city_and_arenas(db_session)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                QUICK_SETUP_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "service_ids": [service_id],
                    "days": [
                        {"day_of_week": 0, "hours": [11], "arena_id": zamok},
                        {"day_of_week": 2, "hours": [9], "arena_id": manege},
                    ],
                    "duration_minutes": 60,
                },
            )
            resp = await client.get(QUICK_SETUP_URL, headers={"X-Telegram-Init-Data": "mock"})

    data = resp.json()
    assert data["multi_arena"] is True
    assert sorted(data["linked_arena_ids"]) == sorted([zamok, manege])
    week_by_day = {d["day_of_week"]: d for d in data["week"]}
    assert week_by_day[0]["arena_id"] == zamok
    assert week_by_day[0]["hours"] == [11]
    assert week_by_day[2]["arena_id"] == manege
