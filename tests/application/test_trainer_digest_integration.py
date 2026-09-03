"""Integration tests for ``get_trainer_daily_digest`` and ``get_trainer_weekly_digest``.

Requires test DB (``alembic upgrade head`` on ``trainer_crm_test``).
Follows fixture pattern from ``test_list_bookings_for_trainer_hub.py`` — seed trainer/service/arena,
then verify aggregator shape and content.
"""
from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.trainer_digest_use_cases import (
    DROUGHT_CONSECUTIVE_DAYS,
    get_trainer_daily_digest,
    get_trainer_weekly_digest,
)
from src.bot.notification_loops import _list_digest_candidates_for_kind
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_arena_city_name, require_seed_service_id


async def _seed_trainer(db_session) -> tuple[int, int, int, int]:
    """Returns (trainer_id, service_id, arena_id, city_id)."""
    arena_id, city_id, _name = await require_seed_arena_city_name(db_session)
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, is_catalog_visible) "
            "VALUES ('active', true) RETURNING id"
        )
    )
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, 'T', 'Digest', 30, :cid)
            """
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
            "VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"
        ),
        {"tid": trainer_id, "aid": arena_id},
    )
    return trainer_id, service_id, arena_id, city_id


async def _insert_client(db_session, first_name: str = "Cli") -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, :fn, 'Ent', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "fn": first_name, "phone": phone, "pn": phone_n},
    )
    (cid,) = r.fetchone()
    return int(cid)


async def _book(
    db_session,
    *,
    trainer_id: int,
    client_id: int,
    service_id: int,
    slot_date: date,
    start: time,
    end: time,
    status: str = "confirmed",
    price_cents: int = 5000,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :s, :e, 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_date, "s": start, "e": end},
    )
    (slot_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, booking_price_cents)
            VALUES (:sid, :tid, :cid, :svc, :st, :price) RETURNING id
            """
        ),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "svc": service_id,
            "st": status,
            "price": price_cents,
        },
    )
    (booking_id,) = r.fetchone()
    return int(booking_id)


# =============================================================================
# Daily digest
# =============================================================================


@pytest.mark.asyncio
async def test_daily_digest_empty_day(db_session) -> None:
    trainer_id, *_ = await _seed_trainer(db_session)
    await db_session.commit()
    d = await get_trainer_daily_digest(db_session, trainer_id, date.today())
    assert d["sessions_count"] == 0
    assert d["sessions"] == []
    assert d["first_session_start"] is None
    assert d["gaps"] == []
    assert d["first_timers_count"] == 0
    assert d["pending_confirmations_count"] == 0


@pytest.mark.asyncio
async def test_daily_digest_run_sheet_and_gap(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session, "Oleg")
    c2 = await _insert_client(db_session, "Irina")
    c3 = await _insert_client(db_session, "Katya")
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=today, start=time(9, 0), end=time(10, 0))
    await _book(db_session, trainer_id=trainer_id, client_id=c2, service_id=service_id,
                slot_date=today, start=time(10, 30), end=time(11, 30))
    # 2.5h gap between 11:30 and 14:00 — should surface
    await _book(db_session, trainer_id=trainer_id, client_id=c3, service_id=service_id,
                slot_date=today, start=time(14, 0), end=time(15, 0))
    await db_session.commit()

    d = await get_trainer_daily_digest(db_session, trainer_id, today)
    assert d["sessions_count"] == 3
    assert [s["client_name"] for s in d["sessions"]] == ["Oleg Ent", "Irina Ent", "Katya Ent"]
    assert d["first_session_start"] == time(9, 0)
    assert len(d["gaps"]) == 1
    assert d["gaps"][0]["from_time"] == time(11, 30)
    assert d["gaps"][0]["to_time"] == time(14, 0)
    assert d["gaps"][0]["duration_minutes"] == 150
    assert d["first_timers_count"] == 3  # all three have no prior bookings
    assert d["pending_confirmations_count"] == 0


@pytest.mark.asyncio
async def test_daily_digest_excludes_cancelled(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session)
    c2 = await _insert_client(db_session)
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=today, start=time(9, 0), end=time(10, 0), status="cancelled")
    await _book(db_session, trainer_id=trainer_id, client_id=c2, service_id=service_id,
                slot_date=today, start=time(11, 0), end=time(12, 0), status="declined")
    await db_session.commit()

    d = await get_trainer_daily_digest(db_session, trainer_id, today)
    assert d["sessions_count"] == 0


@pytest.mark.asyncio
async def test_daily_digest_first_timer_detection(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    returning = await _insert_client(db_session, "Repeat")
    newbie = await _insert_client(db_session, "Fresh")
    # Past completed booking 10 days ago — returning client is NOT first-timer today.
    await _book(db_session, trainer_id=trainer_id, client_id=returning, service_id=service_id,
                slot_date=today - timedelta(days=10), start=time(9, 0), end=time(10, 0),
                status="completed")
    await _book(db_session, trainer_id=trainer_id, client_id=returning, service_id=service_id,
                slot_date=today, start=time(10, 0), end=time(11, 0))
    await _book(db_session, trainer_id=trainer_id, client_id=newbie, service_id=service_id,
                slot_date=today, start=time(11, 0), end=time(12, 0))
    await db_session.commit()

    d = await get_trainer_daily_digest(db_session, trainer_id, today)
    by_name = {s["client_name"]: s for s in d["sessions"]}
    assert by_name["Repeat Ent"]["is_first_time"] is False
    assert by_name["Fresh Ent"]["is_first_time"] is True
    assert d["first_timers_count"] == 1


@pytest.mark.asyncio
async def test_daily_digest_pending_confirmations(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session)
    c2 = await _insert_client(db_session)
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=today, start=time(9, 0), end=time(10, 0), status="pending")
    await _book(db_session, trainer_id=trainer_id, client_id=c2, service_id=service_id,
                slot_date=today, start=time(11, 0), end=time(12, 0), status="confirmed")
    await db_session.commit()

    d = await get_trainer_daily_digest(db_session, trainer_id, today)
    assert d["sessions_count"] == 2
    assert d["pending_confirmations_count"] == 1


# =============================================================================
# Weekly digest
# =============================================================================


@pytest.mark.asyncio
async def test_weekly_past_cash_earnings(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session)
    # Completed 2 days ago, no pass/cert credits → cash.
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=today - timedelta(days=2), start=time(9, 0), end=time(10, 0),
                status="completed", price_cents=6000)
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, today)
    assert w["past_week"]["completed_count"] == 1
    assert w["past_week"]["cash_cents"] == 6000
    assert w["past_week"]["pass_sessions_count"] == 0
    assert w["past_week"]["cert_cents"] == 0


@pytest.mark.asyncio
async def test_weekly_upcoming_empty_days_and_heaviest(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session)
    c2 = await _insert_client(db_session)
    up_start = today + timedelta(days=1)
    # Two bookings on up_start, one on up_start+3; other days empty.
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=up_start, start=time(9, 0), end=time(10, 0))
    await _book(db_session, trainer_id=trainer_id, client_id=c2, service_id=service_id,
                slot_date=up_start, start=time(11, 0), end=time(12, 0))
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=up_start + timedelta(days=3), start=time(15, 0), end=time(16, 0))
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, today)
    assert w["upcoming_week"]["sessions_count"] == 3
    assert len(w["upcoming_week"]["empty_days"]) == 5  # 7 days - 2 busy days
    assert w["upcoming_week"]["heaviest_day"] == {"date": up_start, "count": 2}


@pytest.mark.asyncio
async def test_weekly_drought_not_triggered_with_recent_bookings(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    c1 = await _insert_client(db_session)
    await _book(db_session, trainer_id=trainer_id, client_id=c1, service_id=service_id,
                slot_date=today - timedelta(days=1), start=time(9, 0), end=time(10, 0),
                status="completed")
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, today)
    assert w["drought"]["triggered"] is False
    assert w["drought"]["consecutive_skip_days"] == 0


@pytest.mark.asyncio
async def test_weekly_drought_ladder_case_catalog_hidden(db_session) -> None:
    trainer_id, *_ = await _seed_trainer(db_session)
    # Force catalog hidden → drought case 2.
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = false WHERE id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, date.today())
    assert w["drought"]["triggered"] is True
    assert w["drought"]["consecutive_skip_days"] >= DROUGHT_CONSECUTIVE_DAYS
    assert w["drought"]["case"] == 2
    assert w["drought"]["case_key"] == "catalog_hidden"


@pytest.mark.asyncio
async def test_weekly_drought_ladder_case_no_available_slots(db_session) -> None:
    trainer_id, *_ = await _seed_trainer(db_session)
    # Catalog visible (default), no open requests, no slots → case 3 ("no_available_slots").
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, date.today())
    assert w["drought"]["triggered"] is True
    assert w["drought"]["case"] == 3
    assert w["drought"]["case_key"] == "no_available_slots"
    assert w["drought"]["data"]["horizon_days"] > 0


@pytest.mark.asyncio
async def test_weekly_drought_ladder_case_dormant_clients(db_session) -> None:
    trainer_id, service_id, *_ = await _seed_trainer(db_session)
    today = date.today()
    dormant = await _insert_client(db_session, "Sleeper")
    # Completed 30 days ago, no future bookings → dormant.
    await _book(db_session, trainer_id=trainer_id, client_id=dormant, service_id=service_id,
                slot_date=today - timedelta(days=30), start=time(9, 0), end=time(10, 0),
                status="completed")
    # Add an available future slot to bypass case 3.
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '18:00', TIME '19:00', 'available')
            """
        ),
        {"tid": trainer_id, "d": today + timedelta(days=2)},
    )
    await db_session.commit()

    w = await get_trainer_weekly_digest(db_session, trainer_id, today)
    assert w["drought"]["triggered"] is True
    assert w["drought"]["case"] == 4
    assert w["drought"]["case_key"] == "dormant_clients"
    assert len(w["drought"]["data"]["clients"]) == 1
    assert w["drought"]["data"]["clients"][0]["client_name"] == "Sleeper Ent"


async def _seed_bare_trainer(
    db_session,
    *,
    status: str,
    telegram_id: int | None,
    digest_enabled: bool = True,
) -> int:
    """Minimal trainer row — no profile/services/arenas — for digest-candidates gating tests."""
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, telegram_id, digest_enabled, is_catalog_visible)
            VALUES (:status, :tg, :digest_enabled, false)
            RETURNING id
            """
        ),
        {"status": status, "tg": telegram_id, "digest_enabled": digest_enabled},
    )
    (trainer_id,) = r.fetchone()
    return trainer_id


async def _insert_todays_slot_and_booking(db_session, trainer_id: int, today: date) -> None:
    """One confirmed session today so the digest has something to report (not required by
    ``_list_digest_candidates_for_kind`` itself — the candidate list doesn't look at bookings —
    but keeps the fixture honest for anyone reusing it against the full digest aggregator."""
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '09:00', TIME '10:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": today},
    )
    (slot_id,) = r.fetchone()
    client_id = await _insert_client(db_session, "Today")
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )


@pytest.mark.asyncio
async def test_digest_candidates_include_pending_profile_trainer(db_session) -> None:
    """TASK-026 AC-001: onboarding v2 — a still-unmoderated trainer must still get the digest."""
    today = date.today()
    tg = unique_test_telegram_id()
    trainer_id = await _seed_bare_trainer(db_session, status="pending_profile", telegram_id=tg)
    await _insert_todays_slot_and_booking(db_session, trainer_id, today)
    await db_session.commit()

    rows = await _list_digest_candidates_for_kind(db_session, today, "daily")
    assert trainer_id in {r["trainer_id"] for r in rows}


@pytest.mark.asyncio
async def test_digest_candidates_exclude_deactivated_trainer(db_session) -> None:
    """TASK-026 AC-003 (digest half): explicit deactivation is the only status that closes it."""
    today = date.today()
    tg = unique_test_telegram_id()
    trainer_id = await _seed_bare_trainer(db_session, status="deactivated", telegram_id=tg)
    await db_session.commit()

    rows = await _list_digest_candidates_for_kind(db_session, today, "daily")
    assert trainer_id not in {r["trainer_id"] for r in rows}


@pytest.mark.asyncio
async def test_digest_candidates_exclude_trainer_without_telegram(db_session) -> None:
    """TASK-026 AC-004 (digest half): no telegram_id means no delivery channel at all."""
    today = date.today()
    trainer_id = await _seed_bare_trainer(db_session, status="active", telegram_id=None)
    await db_session.commit()

    rows = await _list_digest_candidates_for_kind(db_session, today, "daily")
    assert trainer_id not in {r["trainer_id"] for r in rows}
