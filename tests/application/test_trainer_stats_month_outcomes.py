"""Calendar-month session outcome KPIs on trainer stats dashboard."""

from datetime import date, timedelta

import pytest
from sqlalchemy import text

from src.application.stats_use_cases import get_trainer_stats_dashboard

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer(db_session) -> tuple[int, int, int]:
    """trainer_id, client_id, service_id."""
    arena_id, city_id, _ = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'T', 'R', 30, :cid)
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
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    return trainer_id, client_id, service_id


async def _add_booking(
    db_session,
    *,
    trainer_id: int,
    client_id: int,
    service_id: int,
    slot_date: date,
    booking_status: str,
    cancellation_source: str | None = None,
    slot_end_past: bool = True,
) -> None:
    arena_id, _, _ = await require_seed_arena_city_name(db_session)
    end_time = "09:00:00" if slot_end_past else "23:59:00"
    r = await db_session.execute(
        text(
            f"""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, arena_id)
            VALUES (:tid, :d, TIME '08:00', TIME '{end_time}', 'booked', :aid)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "aid": arena_id},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, cancellation_source)
            VALUES (:sid, :tid, :cid, :svc, :st, :cs)
            """
        ),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "svc": service_id,
            "st": booking_status,
            "cs": cancellation_source,
        },
    )


@pytest.mark.asyncio
async def test_trainer_stats_month_outcomes_calendar_month_and_rate(db_session) -> None:
    today = date.today()
    if today.day < 8:
        pytest.skip("Need at least 8 days into month for stable past/future fixtures")
    month_start = today.replace(day=1)
    past_day = today - timedelta(days=5)
    future_day = today + timedelta(days=7)
    if future_day.month != today.month:
        pytest.skip("Need future slot still inside current calendar month")

    trainer_id, client_id, service_id = await _seed_trainer(db_session)
    for st in ("completed", "completed", "completed", "cancelled", "declined"):
        await _add_booking(
            db_session,
            trainer_id=trainer_id,
            client_id=client_id,
            service_id=service_id,
            slot_date=past_day,
            booking_status=st,
        )
    await _add_booking(
        db_session,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        slot_date=future_day,
        booking_status="confirmed",
        slot_end_past=False,
    )
    await _add_booking(
        db_session,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        slot_date=past_day,
        booking_status="cancelled",
        cancellation_source="roster_detach",
    )
    await db_session.commit()

    data = await get_trainer_stats_dashboard(db_session, trainer_id)
    assert data["month_start"] == month_start
    assert data["bookings_completed_month"] == 3
    assert data["cancellations_month"] == 1
    assert data["declines_month"] == 1
    assert data["sessions_outcome_month"] == 5
    assert data["cancel_decline_rate_month_pct"] == 40.0
