"""
День ноль: первые часы одним тапом с главной — POST /api/webapp/trainer/hub/first-hours.

Проверяется продуктовое обещание, а не форма ответа: тренер, у которого после онбординга
нет ни одного слота, одним нажатием получает две недели живых окон — и при этом ручка
не трогает ничего, кроме расписания. Последнее важно: услуги, роли и город он уже выбрал,
и экран дня ноль спрашивает только про время.
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

FIRST_HOURS_URL = "/api/webapp/trainer/hub/first-hours"


def _fresh_trainer_telegram_id() -> int:
    return 5_410_000_000 + (uuid.uuid4().int % 4_000_000_000)


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


async def _trainer_after_onboarding_without_hours(db_session, telegram_id: int) -> int:
    """Профиль сохранён, услуга привязана, расписания нет — ровно состояние дня ноль."""
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": telegram_id, "id": trainer_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, session_duration_minutes, onboarding_completed_at)
            VALUES (:tid, 60, now())
            ON CONFLICT (trainer_id) DO UPDATE SET
                session_duration_minutes = 60,
                onboarding_completed_at = now()
            """
        ),
        {"tid": trainer_id},
    )
    r_svc = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    svc = r_svc.fetchone()
    if not svc:
        pytest.skip("need services in DB")
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id) VALUES (:t, :s) "
            "ON CONFLICT DO NOTHING"
        ),
        {"t": trainer_id, "s": int(svc[0])},
    )
    await db_session.commit()
    await _grant_crm(db_session, trainer_id)
    return trainer_id


async def _post_preset(telegram_id: int, preset: str):
    with patch_trainer_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(
                FIRST_HOURS_URL,
                headers={"X-Telegram-Init-Data": "mock"},
                json={"preset": preset},
            )


@pytest.mark.asyncio
async def test_preset_turns_an_empty_schedule_into_bookable_weeks(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)

    resp = await _post_preset(tg, "weekday_evening")

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["days_with_slots"] == 3, "пн, ср, пт"
    assert data["open_slots_ahead"] > 0, "окна должны быть доступны к записи прямо сейчас"

    r = await db_session.execute(
        text("SELECT COUNT(*) FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == 9, "3 дня по 3 часа"

    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE trainer_id = :t AND status = 'available'"),
        {"t": trainer_id},
    )
    assert r.scalar() > 0


@pytest.mark.asyncio
async def test_horizon_matches_the_two_weeks_actually_written(app_use_test_db, db_session) -> None:
    """«12 окон до 19 октября» — дата на экране обязана совпасть с последним слотом."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)

    resp = await _post_preset(tg, "weekend_morning")
    assert resp.status_code == 200, resp.text
    horizon = date.fromisoformat(resp.json()["horizon_date"])

    r = await db_session.execute(
        text("SELECT MAX(slot_date) FROM slots WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    last_slot = r.scalar()
    assert last_slot is not None
    assert last_slot <= horizon
    assert horizon - last_slot < timedelta(days=7), "горизонт не должен уезжать в пустоту"


@pytest.mark.asyncio
async def test_answer_about_time_does_not_touch_services_or_city(app_use_test_db, db_session) -> None:
    """Экран дня ноль спрашивает только про время — остальное тренер уже выбрал."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)

    r = await db_session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :t ORDER BY service_id"),
        {"t": trainer_id},
    )
    services_before = [int(x[0]) for x in r.fetchall()]
    assert services_before, "фикстура должна дать тренеру услугу"

    r_city = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    city_row = r_city.fetchone()
    if city_row:
        await db_session.execute(
            text("UPDATE trainer_profiles SET city_id = :c WHERE trainer_id = :t"),
            {"c": int(city_row[0]), "t": trainer_id},
        )
        await db_session.commit()

    resp = await _post_preset(tg, "weekday_evening")
    assert resp.status_code == 200, resp.text

    r = await db_session.execute(
        text("SELECT service_id FROM trainer_services WHERE trainer_id = :t ORDER BY service_id"),
        {"t": trainer_id},
    )
    assert [int(x[0]) for x in r.fetchall()] == services_before

    if city_row:
        r = await db_session.execute(
            text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :t"),
            {"t": trainer_id},
        )
        assert int(r.scalar()) == int(city_row[0]), "город не должен обнуляться"


@pytest.mark.asyncio
async def test_slots_use_the_duration_the_trainer_already_chose(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)
    await db_session.execute(
        text("UPDATE trainer_profiles SET session_duration_minutes = 90 WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    await db_session.commit()

    resp = await _post_preset(tg, "weekday_evening")
    assert resp.status_code == 200, resp.text

    r = await db_session.execute(
        text(
            "SELECT DISTINCT (EXTRACT(EPOCH FROM (end_time - start_time)) / 60)::int "
            "FROM slots WHERE trainer_id = :t"
        ),
        {"t": trainer_id},
    )
    assert [int(x[0]) for x in r.fetchall()] == [90]

    # Окно 18:00–21:00 вмещает одно занятие в 90 минут без наложения — именно одно,
    # а не три часовых старта поверх друг друга.
    r = await db_session.execute(
        text(
            "SELECT DISTINCT start_time FROM trainer_schedule_templates WHERE trainer_id = :t"
        ),
        {"t": trainer_id},
    )
    assert [str(x[0]) for x in r.fetchall()] == ["18:00:00"]


@pytest.mark.asyncio
async def test_unknown_preset_is_rejected_without_writing_anything(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)

    resp = await _post_preset(tg, "whenever")

    assert resp.status_code == 400, resp.text
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == 0


@pytest.mark.asyncio
async def test_repeating_the_same_answer_does_not_duplicate_the_week(app_use_test_db, db_session) -> None:
    """Двойной тап по пресету — обычное дело на мобильном; он не должен удваивать расписание."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _trainer_after_onboarding_without_hours(db_session, tg)

    first = await _post_preset(tg, "weekday_evening")
    assert first.status_code == 200, first.text
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE trainer_id = :t"), {"t": trainer_id}
    )
    after_first = int(r.scalar())

    second = await _post_preset(tg, "weekday_evening")
    assert second.status_code == 200, second.text
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE trainer_id = :t"), {"t": trainer_id}
    )
    assert int(r.scalar()) == after_first
