"""
Trainer hub list (PRD E1): session visible until slot end; current window sorts first.
Requires test DB (alembic upgrade head).
"""
from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    get_trainer_hub_session_summary_counts,
    list_bookings_for_trainer,
)

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer_with_service(db_session) -> tuple[int, int]:
    """trainer_id, service_id."""
    arena_id, city_id, _arena_name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
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
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 1000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    return trainer_id, service_id


@pytest.mark.asyncio
async def test_hub_excludes_booking_after_slot_end_today(db_session) -> None:
    """Ended slot on calendar today must not appear (replaces loose slot_date >= today only)."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
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
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, CURRENT_DATE - 1, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert bookings == []


@pytest.mark.asyncio
async def test_hub_sorts_in_session_booking_before_later_same_day(db_session) -> None:
    """Within [start,end) now is first; later same-day slot follows."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    clients: list[int] = []
    for _ in range(2):
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
        (cid,) = r.fetchone()
        clients.append(cid)

    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                ((CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk') - INTERVAL '45 minutes')::time,
                ((CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk') + INTERVAL '2 hours')::time,
                'booked'
            )
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_now,) = r.fetchone()

    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                TIME '23:00',
                TIME '23:45',
                'booked'
            )
            RETURNING id
        """),
        {"tid": trainer_id},
    )
    (slot_later,) = r.fetchone()

    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_later, "tid": trainer_id, "cid": clients[1], "svc": service_id},
    )
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            RETURNING id
        """),
        {"sid": slot_now, "tid": trainer_id, "cid": clients[0], "svc": service_id},
    )
    (bid_now,) = r.fetchone()
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert len(bookings) == 2
    assert bookings[0]["id"] == bid_now
    assert bookings[0]["hub_in_session"] is True
    assert bookings[1]["hub_in_session"] is False


@pytest.mark.asyncio
async def test_hub_tomorrow_still_listed(db_session) -> None:
    """Future day bookings unchanged."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tomorrow = date.today() + timedelta(days=1)
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
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :et, 'booked')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow, "st": time(10, 0), "et": time(11, 0)},
    )
    (slot_id,) = r.fetchone()
    await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
        """),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    bookings = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    assert len(bookings) == 1
    assert bookings[0]["hub_in_session"] is False
    assert bookings[0]["service_id"] == service_id


@pytest.mark.asyncio
async def test_hub_first_client_online_pending_only_before_any_notified_push(db_session) -> None:
    """Hub flag: pending + no notified_at yet + no prior booking already pushed to trainer."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tomorrow = date.today() + timedelta(days=1)
    tg_a = unique_test_telegram_id()
    phone_a, phone_n_a = belarus_test_phone(tg_a)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'A', 'One', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg_a, "phone": phone_a, "pn": phone_n_a},
    )
    (client_a,) = r.fetchone()
    tg_b = unique_test_telegram_id()
    phone_b, phone_n_b = belarus_test_phone(tg_b)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'B', 'Two', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg_b, "phone": phone_b, "pn": phone_n_b},
    )
    (client_b,) = r.fetchone()

    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'available')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_a,) = r.fetchone()
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '12:00', TIME '13:00', 'available')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_b,) = r.fetchone()

    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'pending')
            RETURNING id
        """),
        {"sid": slot_a, "tid": trainer_id, "cid": client_a, "svc": service_id},
    )
    (bid_first,) = r.fetchone()
    r = await db_session.execute(
        text("""
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'pending')
            RETURNING id
        """),
        {"sid": slot_b, "tid": trainer_id, "cid": client_b, "svc": service_id},
    )
    (bid_second,) = r.fetchone()
    await db_session.commit()

    rows = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    by_id = {b["id"]: b for b in rows}
    assert by_id[bid_first]["first_client_online_pending"] is True
    assert by_id[bid_second]["first_client_online_pending"] is True

    await db_session.execute(
        text("UPDATE bookings SET notified_at = NOW() WHERE id = :id"),
        {"id": bid_first},
    )
    await db_session.commit()

    rows2 = await list_bookings_for_trainer(db_session, trainer_id, limit=50)
    by_id2 = {b["id"]: b for b in rows2}
    assert by_id2[bid_first]["first_client_online_pending"] is False
    assert by_id2[bid_second]["first_client_online_pending"] is False


@pytest.mark.asyncio
async def test_hub_session_summary_week_total_not_capped_by_list_limit(db_session) -> None:
    """Hub tiles must count the full Minsk calendar week, not the truncated /trainer/bookings LIMIT."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    for i in range(5):
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
        (cid,) = r.fetchone()
        r = await db_session.execute(
            text(
                """
                WITH m AS (SELECT CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk' AS n)
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                SELECT :tid,
                       (n + make_interval(hours => 2 + (:i * 2)))::date,
                       (n + make_interval(hours => 2 + (:i * 2)))::time,
                       (n + make_interval(hours => 3 + (:i * 2)))::time,
                       'booked'
                FROM m
                RETURNING id
                """
            ),
            {"tid": trainer_id, "i": i},
        )
        (sid,) = r.fetchone()
        await db_session.execute(
            text(
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
                VALUES (:sid, :tid, :cid, :svc, 'confirmed')
                """
            ),
            {"sid": sid, "tid": trainer_id, "cid": cid, "svc": service_id},
        )
    await db_session.commit()

    listed = await list_bookings_for_trainer(db_session, trainer_id, limit=2)
    assert len(listed) == 2

    summary = await get_trainer_hub_session_summary_counts(db_session, trainer_id)
    assert summary["week_total"] == 5


@pytest.mark.asyncio
async def test_hub_session_summary_group_slot_counts_once(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    clients: list[int] = []
    for _ in range(2):
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
        (cid,) = r.fetchone()
        clients.append(int(cid))
    r = await db_session.execute(
        text(
            """
            WITH m AS (SELECT CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk' AS n)
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            SELECT :tid,
                   (n + make_interval(hours => 4))::date,
                   (n + make_interval(hours => 4))::time,
                   (n + make_interval(hours => 5))::time,
                   'booked',
                   3
            FROM m
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_id,) = r.fetchone()
    for cid in clients:
        await db_session.execute(
            text(
                """
                INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
                VALUES (:sid, :tid, :cid, :svc, 'confirmed')
                """
            ),
            {"sid": slot_id, "tid": trainer_id, "cid": cid, "svc": service_id},
        )
    await db_session.commit()

    summary = await get_trainer_hub_session_summary_counts(db_session, trainer_id)
    assert summary["week_total"] == 1


@pytest.mark.asyncio
async def test_hub_session_summary_today_total_includes_completed_sessions(db_session) -> None:
    """Hub «всего» counts sessions that already ended today; «осталось» only not-yet-started."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk'))::int AS h
            """
        )
    )
    (h,) = r.fetchone()
    if h is None or h < 11 or h >= 19:
        pytest.skip("Need Minsk hour in [11, 19) for fixed 08:00 past and 20:00 future on same date")

    clients: list[int] = []
    for _ in range(2):
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
        (cid,) = r.fetchone()
        clients.append(int(cid))

    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            SELECT :tid,
                   (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                   TIME '08:00',
                   TIME '09:00',
                   'booked'
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_past,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            SELECT :tid,
                   (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                   TIME '20:00',
                   TIME '21:00',
                   'booked'
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_future,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_past, "tid": trainer_id, "cid": clients[0], "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_future, "tid": trainer_id, "cid": clients[1], "svc": service_id},
    )
    await db_session.commit()

    summary = await get_trainer_hub_session_summary_counts(db_session, trainer_id)
    assert summary["today_total"] == 2
    assert summary["today_remaining"] == 1
    assert summary["week_total"] >= 2
    assert summary["week_remaining"] >= 1


@pytest.mark.asyncio
async def test_hub_session_summary_counts_completed_booking_rows(db_session) -> None:
    """After mark-complete, booking is ``completed`` — must still appear in «всего», not in «осталось»."""
    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    r = await db_session.execute(
        text(
            """
            SELECT EXTRACT(HOUR FROM (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk'))::int AS h
            """
        )
    )
    (h,) = r.fetchone()
    if h is None or h < 11 or h >= 19:
        pytest.skip("Need Minsk hour in [11, 19) for fixed 08:00 past and 20:00 future on same date")

    clients: list[int] = []
    for _ in range(2):
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
        (cid,) = r.fetchone()
        clients.append(int(cid))

    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            SELECT :tid,
                   (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                   TIME '08:00',
                   TIME '09:00',
                   'booked'
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_past,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            SELECT :tid,
                   (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                   TIME '20:00',
                   TIME '21:00',
                   'booked'
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (slot_future,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_past, "tid": trainer_id, "cid": clients[0], "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_future, "tid": trainer_id, "cid": clients[1], "svc": service_id},
    )
    await db_session.commit()

    summary = await get_trainer_hub_session_summary_counts(db_session, trainer_id)
    assert summary["today_total"] == 2
    assert summary["today_remaining"] == 1
