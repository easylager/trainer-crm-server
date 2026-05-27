"""GET/POST trainer booking problem (PRD E2). Requires DB migrated through booking_problem_reports."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta, time
from typing import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal


def _fresh_trainer_telegram_id() -> int:
    import uuid

    return 5_200_000_000 + (uuid.uuid4().int % 4_000_000_000)


@contextmanager
def patch_trainer_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


@pytest.mark.asyncio
@patch(
    "src.api.routes.webapp.send_booking_problem_telegram_notifications",
    new_callable=AsyncMock,
)
async def test_trainer_booking_problem_options_and_submit(
    mock_problem_notify,
    app_use_test_db,
    db_session,
) -> None:
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
            VALUES (:tid, 'T', 'P', 30, :cid)
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
            r0 = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}/problem-options",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r0.status_code == 200
    jo = r0.json()
    assert jo.get("payment_class") == "NONE"
    assert jo.get("pass_cert_no_show_policy") is None
    assert jo.get("already_reported") is False
    assert len(jo.get("presets") or []) == 2
    assert jo["presets"][0]["id"] == "A1"

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                f"/api/webapp/trainer/bookings/{booking_id}/problem",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"preset_id": "A1", "note": "test", "source": "test"},
            )
    assert r1.status_code == 200
    assert r1.json().get("success") is True
    mock_problem_notify.assert_awaited_once()

    rchk = await db_session.execute(
        text("SELECT problematic FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    assert rchk.scalar() is False

    rb = await db_session.execute(
        text("SELECT status FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert rb.scalar() == "no_show"
    rbl = await db_session.execute(
        text("SELECT blacklist_candidate FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert rbl.scalar() is False

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r2 = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r2.status_code == 200
    assert r2.json().get("problem_reported") is True

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r3 = await client.post(
                f"/api/webapp/trainer/bookings/{booking_id}/problem",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"preset_id": "A1"},
            )
    assert r3.status_code == 409


@pytest.mark.asyncio
async def test_trainer_booking_problem_one_off_class(app_use_test_db, db_session) -> None:
    """ONE_OFF when booking has tariff snapshot without pass/cert (E3 T3.1)."""
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
            VALUES (:tid, 'T', 'P', 30, :cid)
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
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, booking_price_cents)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed', :bpc)
            RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id, "bpc": 8_000},
    )
    (booking_id,) = r.fetchone()
    await db_session.commit()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r0 = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}/problem-options",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r0.status_code == 200
    jo = r0.json()
    assert jo.get("payment_class") == "ONE_OFF"
    assert jo.get("pass_cert_no_show_policy") is None
    assert jo["presets"][0]["id"] == "A1"


@pytest.mark.asyncio
@patch(
    "src.api.routes.webapp.send_booking_client_no_show_telegram_notifications",
    new_callable=AsyncMock,
)
@patch(
    "src.api.routes.webapp.send_booking_problem_telegram_notifications",
    new_callable=AsyncMock,
)
async def test_trainer_booking_problem_pass_branch_policy_in_options(
    mock_problem_notify,
    mock_no_show_notify,
    app_use_test_db,
    db_session,
) -> None:
    """PASS branch returns trainer no-show policy; B1 carries policy key (E3 T3.2)."""
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
            INSERT INTO trainer_profiles (
              trainer_id, first_name, last_name, age, city_id, pass_cert_no_show_policy
            )
            VALUES (:tid, 'T', 'P', 30, :cid, 'skip')
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
    rpp = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (
              trainer_id, name, sessions_total, price_cents, is_active, sort_order
            )
            VALUES (:tid, 'Ab5', 5, 50_000, true, 0)
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (ppid,) = rpp.fetchone()
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_product_services (pass_product_id, service_id)
            VALUES (:ppid, :sid)
            """
        ),
        {"ppid": ppid, "sid": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO pass_instances (
              client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status
            )
            VALUES (:cid, :ppid, 5, 5, 50000, 'active')
            """
        ),
        {"cid": client_id, "ppid": ppid},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r0 = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}/problem-options",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r0.status_code == 200
    jo = r0.json()
    assert jo.get("payment_class") == "PASS"
    assert jo.get("pass_cert_no_show_policy") == "skip"
    assert jo.get("pass_cert_no_show_flow") is False
    assert len(jo.get("presets") or []) == 0
    assert len(jo.get("pass_cert_deduct_options") or []) == 0

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_bad = await client.post(
                f"/api/webapp/trainer/bookings/{booking_id}/problem",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"preset_id": "B1", "source": "test"},
            )
    assert r_bad.status_code == 400
    mock_problem_notify.assert_not_called()

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_co = await client.get(
                f"/api/webapp/trainer/bookings/{booking_id}/client-no-show-options",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert r_co.status_code == 200
    co = r_co.json()
    assert co.get("phase") == "before_complete"
    assert co.get("already_recorded") is False

    with patch_trainer_webapp_init(trainer_tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                f"/api/webapp/trainer/bookings/{booking_id}/client-no-show",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={"choice": "skip_redeem", "source": "test"},
            )
    assert r1.status_code == 200
    assert r1.json().get("success") is True
    mock_no_show_notify.assert_awaited_once()
    assert mock_no_show_notify.await_args.args[1] == booking_id

    rchk = await db_session.execute(
        text("SELECT problematic FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    assert rchk.scalar() is False

    rsb = await db_session.execute(
        text("SELECT status FROM bookings WHERE id = :bid"),
        {"bid": booking_id},
    )
    assert rsb.scalar() == "no_show"

    rpr = await db_session.execute(
        text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    assert rpr.fetchone() is None

    rcns = await db_session.execute(
        text(
            "SELECT deduct_resolution FROM booking_client_no_show WHERE booking_id = :bid"
        ),
        {"bid": booking_id},
    )
    assert (rcns.scalar() or "").strip() == "skip"
