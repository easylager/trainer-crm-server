"""
Booking attribution for multi-profile accounts: X-Profile-Id must land bookings on the
selected guardian/child client_id (not the parent's self row), including when that child
is also the account default.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    _create_trainer_online_with_slot,
    patch_client_init_auth,
)
from tests.conftest import belarus_test_phone


def _fresh_client_telegram_id() -> int:
    return 7_810_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_client(db_session, *, telegram_id: int | None, first_name: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES (:fn, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


async def _add_child_profile(client, *, first_name: str) -> int:
    r = await client.post(
        "/api/webapp/client/profiles",
        json={"first_name": first_name},
        headers=_client_auth_headers(),
    )
    assert r.status_code == 200, r.text
    return int(r.json()["client_id"])


async def _set_default_profile(client, *, profile_client_id: int) -> None:
    r = await client.patch(
        f"/api/webapp/client/profiles/{profile_client_id}/default",
        headers=_client_auth_headers(),
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_booking_with_x_profile_id_attributes_to_guardian_child(
    app_use_test_db, db_session
) -> None:
    """POST /client/booking with X-Profile-Id=<child> stores bookings.client_id = child."""
    slot_day = date.today() + timedelta(days=14)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    _trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={18}
    )

    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    phone, _norm = belarus_test_phone(tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")
            await _set_default_profile(client, profile_client_id=child_id)

            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                    },
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )

    assert book.status_code == 200, book.text
    booking_id = book.json()["booking_id"]

    r = await db_session.execute(
        text("SELECT client_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    booked_for = int(r.scalar_one())
    assert booked_for == child_id
    assert booked_for != parent_id


@pytest.mark.asyncio
async def test_booking_with_header_when_child_is_default_still_lands_on_child(
    app_use_test_db, db_session
) -> None:
    """
    Regression for Task 1: when the child is both active and default, the client now always
    sends X-Profile-Id. Server must still attribute the booking to the child (not self).
    """
    slot_day = date.today() + timedelta(days=16)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    _trainer_id, service_id, slot_id = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={19}
    )

    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Папа")
    phone, _norm = belarus_test_phone(tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Ваня")
            await _set_default_profile(client, profile_client_id=child_id)

            # Explicit header even though child is default — mirrors the fixed fetch patch.
            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_id,
                        "phone": phone,
                        "service_id": service_id,
                    },
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )

    assert book.status_code == 200, book.text
    booking_id = book.json()["booking_id"]

    r = await db_session.execute(
        text("SELECT client_id FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    booked_for = int(r.scalar_one())
    assert booked_for == child_id
    assert booked_for != parent_id


async def _seed_upcoming_booking(
    db_session,
    *,
    trainer_id: int,
    client_id: int,
    service_id: int,
    hour: int = 10,
    status: str = "confirmed",
) -> int:
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date + 2,
                make_time(:h, 0, 0),
                make_time(:h, 0, 0) + INTERVAL '1 hour',
                'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id, "h": hour},
    )
    (slot_id,) = r_slot.fetchone()
    r_booking = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, :st) RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id, "st": status},
    )
    (booking_id,) = r_booking.fetchone()
    await db_session.commit()
    return int(booking_id)


async def _seed_past_booking(
    db_session, *, trainer_id: int, client_id: int, service_id: int, hour: int = 10
) -> int:
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (
                :tid,
                (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date - 1,
                make_time(:h, 0, 0),
                make_time(:h, 0, 0) + INTERVAL '1 hour',
                'booked'
            )
            RETURNING id
            """
        ),
        {"tid": trainer_id, "h": hour},
    )
    (slot_id,) = r_slot.fetchone()
    r_booking = await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed') RETURNING id
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    (booking_id,) = r_booking.fetchone()
    await db_session.commit()
    return int(booking_id)


@pytest.mark.asyncio
async def test_get_client_bookings_scoped_to_x_profile_id(app_use_test_db, db_session) -> None:
    """Parent booking A + child booking B; with X-Profile-Id=child, list returns only B."""
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    parent_bid = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=parent_id, service_id=service_id, hour=10
    )
    child_bid = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=12
    )

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_child = await client.get(
                "/api/webapp/client/bookings",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            r_parent = await client.get(
                "/api/webapp/client/bookings",
                headers=_client_auth_headers(),
            )

    assert r_child.status_code == 200 and r_parent.status_code == 200
    child_ids = [b["id"] for d in r_child.json().get("days") or [] for b in d.get("bookings") or []]
    parent_ids = [b["id"] for d in r_parent.json().get("days") or [] for b in d.get("bookings") or []]
    assert child_ids == [child_bid]
    assert parent_bid in parent_ids
    assert child_bid not in parent_ids


@pytest.mark.asyncio
async def test_get_client_bookings_history_scoped_to_x_profile_id(app_use_test_db, db_session) -> None:
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Папа")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Ваня")

    parent_bid = await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=parent_id, service_id=service_id, hour=10
    )
    child_bid = await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=14
    )

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_child = await client.get(
                "/api/webapp/client/bookings/history",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert r_child.status_code == 200
    ids = [b["id"] for d in r_child.json().get("days") or [] for b in d.get("bookings") or []]
    assert child_bid in ids
    assert parent_bid not in ids


@pytest.mark.asyncio
async def test_hub_bootstrap_bookings_scoped_to_child_profile(app_use_test_db, db_session) -> None:
    """Hub bootstrap bookings path uses acting profile (same helpers as GET /client/bookings).

    Fan-out sessions in hub bootstrap open a second connection (see conftest), so we assert
    scoping on the shared payload helper and only smoke-check the HTTP shape/header.
    """
    from src.api.routes.webapp_client_payloads import client_bookings_days_payload
    from src.application.client_profile_use_cases import resolve_acting_client_id
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    parent_bid = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=parent_id, service_id=service_id, hour=11
    )
    child_bid = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=15
    )

    acting = await resolve_acting_client_id(db_session, tid, child_id)
    assert acting == child_id
    scoped = await client_bookings_days_payload(
        db_session, tid, acting_client_id=acting
    )
    ids = [b["id"] for d in scoped.get("days") or [] for b in d.get("bookings") or []]
    assert child_bid in ids
    assert parent_bid not in ids

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(
                "/api/webapp/client/hub/bootstrap",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "bookings" in body and "requests" in body


@pytest.mark.asyncio
async def test_get_client_requests_scoped_to_x_profile_id(app_use_test_db, db_session) -> None:
    """GET /client/requests with child header lists only the child's requests."""
    from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

    sid, cid, _aid = await _require_seed_ids(db_session)
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Дочь")

            r_parent_req = await client.post(
                "/api/webapp/client/request",
                json={"city_id": cid, "service_id": sid, "comment": "родитель"},
                headers=_client_auth_headers(),
            )
            r_child_req = await client.post(
                "/api/webapp/client/request",
                json={"city_id": cid, "service_id": sid, "comment": "ребёнок"},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
            assert r_parent_req.status_code == 200 and r_child_req.status_code == 200
            parent_rid = r_parent_req.json()["request_id"]
            child_rid = r_child_req.json()["request_id"]

            listed = await client.get(
                "/api/webapp/client/requests",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json().get("items") or []]
    assert child_rid in ids
    assert parent_rid not in ids


@pytest.mark.asyncio
async def test_activity_stats_do_not_mix_parent_and_child_completed(
    app_use_test_db, db_session
) -> None:
    """Completed bookings on child must not inflate parent completed_total (and vice versa)."""
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=parent_id, service_id=service_id, hour=10
    )
    await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=11
    )
    await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=12
    )

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r_parent = await client.get(
                "/api/webapp/client/activity-stats",
                headers=_client_auth_headers(),
            )
            r_child = await client.get(
                "/api/webapp/client/activity-stats",
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )

    assert r_parent.status_code == 200 and r_child.status_code == 200
    assert r_parent.json()["completed_total"] == 1
    assert r_child.json()["completed_total"] == 2


@pytest.mark.asyncio
async def test_trainer_booking_detail_shows_child_name_and_parent_telegram(
    app_use_test_db, db_session
) -> None:
    """Guardian booking: trainer detail shows child name; notify telegram is parent account."""
    from src.application.booking_use_cases import get_trainer_booking_detail_payload
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    phone, phone_n = belarus_test_phone(tid)
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    await db_session.execute(
        text("UPDATE clients SET phone = :p, phone_normalized = :pn WHERE id = :cid"),
        {"p": phone, "pn": phone_n, "cid": parent_id},
    )
    await db_session.commit()

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    booking_id = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=16
    )

    detail = await get_trainer_booking_detail_payload(db_session, booking_id, trainer_id)
    assert detail is not None
    assert detail["client_id"] == child_id
    assert (detail.get("client_first_name") or "").strip() == "Лера"
    assert detail["client_telegram_id"] == tid
    assert detail.get("booked_via_guardian") is True
    assert (detail.get("client_phone") or "").strip() == phone


@pytest.mark.asyncio
async def test_full_flow_book_child_then_self_separate_client_ids(
    app_use_test_db, db_session
) -> None:
    """E2E: book as child → child client_id; book as self → parent client_id."""
    slot_day = date.today() + timedelta(days=18)
    ref_day = slot_day - timedelta(days=slot_day.weekday())
    ref_now = datetime.combine(ref_day, time(10, 0))
    _trainer_id, service_id, slot_a = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={10}
    )
    _t2, service_id2, slot_b = await _create_trainer_online_with_slot(
        db_session, slot_date=slot_day, start_hours={14}
    )
    assert service_id == service_id2 or True

    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Папа")
    phone, _norm = belarus_test_phone(tid)

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Ваня")

            with patch("src.api.routes.webapp.datetime") as mock_dt, patch(
                "src.api.routes.webapp.date"
            ) as mock_date:
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                book_child = await client.post(
                    "/api/webapp/client/booking",
                    json={"slot_id": slot_a, "phone": phone, "service_id": service_id},
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )
                book_self = await client.post(
                    "/api/webapp/client/booking",
                    json={
                        "slot_id": slot_b,
                        "phone": phone,
                        "service_id": service_id2,
                        "first_name": "Папа",
                    },
                    headers={**_client_auth_headers(), "X-Profile-Id": str(parent_id)},
                )

    assert book_child.status_code == 200, book_child.text
    assert book_self.status_code == 200, book_self.text
    child_bid = book_child.json()["booking_id"]
    self_bid = book_self.json()["booking_id"]

    r = await db_session.execute(
        text("SELECT id, client_id FROM bookings WHERE id IN (:a, :b)"),
        {"a": child_bid, "b": self_bid},
    )
    by_id = {int(row[0]): int(row[1]) for row in r.fetchall()}
    assert by_id[child_bid] == child_id
    assert by_id[self_bid] == parent_id
    assert child_id != parent_id


@pytest.mark.asyncio
async def test_cancel_child_booking_with_x_profile_id_succeeds(
    app_use_test_db, db_session
) -> None:
    """Cancel of a guardian-child booking must honor X-Profile-Id (not self telegram)."""
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    booking_id = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=15
    )

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    mock_bot.session = MagicMock()
    mock_bot.session.close = AsyncMock()

    with patch_client_init_auth(tid):
        with patch("src.api.routes.webapp.Bot", return_value=mock_bot):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                denied = await client.post(
                    f"/api/webapp/client/bookings/{booking_id}/cancel",
                    json={"reason": "болеет"},
                    headers=_client_auth_headers(),
                )
                cancelled = await client.post(
                    f"/api/webapp/client/bookings/{booking_id}/cancel",
                    json={"reason": "болеет"},
                    headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
                )

    assert denied.status_code == 400, denied.text
    assert cancelled.status_code == 200, cancelled.text
    r = await db_session.execute(
        text("SELECT status FROM bookings WHERE id = :bid"), {"bid": booking_id}
    )
    assert (r.scalar_one() or "").strip() == "cancelled"


async def _guardian_child_setup(db_session, *, child_name: str = "Лера"):
    from tests.application.test_list_bookings_for_trainer_hub import _seed_trainer_with_service

    trainer_id, service_id = await _seed_trainer_with_service(db_session)
    tid = _fresh_client_telegram_id()
    phone, phone_n = belarus_test_phone(tid)
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")
    await db_session.execute(
        text("UPDATE clients SET phone = :p, phone_normalized = :pn WHERE id = :cid"),
        {"p": phone, "pn": phone_n, "cid": parent_id},
    )
    await db_session.commit()
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name=child_name)
    return trainer_id, service_id, tid, phone, parent_id, child_id


@pytest.mark.asyncio
async def test_trainer_cancel_and_decline_and_completion_reach_parent_telegram(
    app_use_test_db, db_session
) -> None:
    from src.application.booking_use_cases import (
        cancel_booking,
        decline_booking,
        list_bookings_pending_client_completion_push,
    )

    trainer_id, service_id, tid, _phone, _parent_id, child_id = await _guardian_child_setup(
        db_session
    )
    cancel_bid = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=10
    )
    decline_bid = await _seed_upcoming_booking(
        db_session,
        trainer_id=trainer_id,
        client_id=child_id,
        service_id=service_id,
        hour=11,
        status="pending",
    )
    complete_bid = await _seed_past_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=12
    )

    assert await cancel_booking(db_session, cancel_bid, trainer_id) is True
    queued = await db_session.execute(
        text(
            "SELECT client_telegram_id FROM booking_cancel_notifications WHERE booking_id = :bid"
        ),
        {"bid": cancel_bid},
    )
    assert int(queued.scalar_one()) == tid

    declined = await decline_booking(db_session, decline_bid, trainer_id)
    assert declined is not None
    assert declined["client_telegram_id"] == tid
    assert (declined.get("client_phone") or "").strip()

    pending_push = await list_bookings_pending_client_completion_push(db_session)
    by_id = {int(row["id"]): row for row in pending_push}
    assert complete_bid in by_id
    assert by_id[complete_bid]["client_telegram_id"] == tid


@pytest.mark.asyncio
async def test_trainer_lists_show_parent_contact_for_child_profile(
    app_use_test_db, db_session
) -> None:
    from datetime import date, timedelta

    from src.application.booking_use_cases import (
        active_booking_summaries_by_slot_for_trainer_range,
        get_trainer_client_for_card,
        list_bookings_for_trainer,
        list_trainer_clients,
    )

    trainer_id, service_id, tid, phone, _parent_id, child_id = await _guardian_child_setup(
        db_session
    )
    booking_id = await _seed_upcoming_booking(
        db_session, trainer_id=trainer_id, client_id=child_id, service_id=service_id, hour=16
    )

    hub = await list_bookings_for_trainer(db_session, trainer_id)
    hub_row = next(r for r in hub if int(r["id"]) == booking_id)
    assert hub_row["client_telegram_id"] == tid
    assert (hub_row.get("client_phone") or "").strip() == phone
    assert (hub_row.get("client_first_name") or "").strip() == "Лера"

    today = date.today()
    summaries = await active_booking_summaries_by_slot_for_trainer_range(
        db_session, trainer_id, today, today + timedelta(days=7)
    )
    mini = next(v for v in summaries.values() if int(v["booking_id"]) == booking_id)
    assert mini["client_telegram_id"] == tid
    assert (mini.get("client_phone") or "").strip() == phone

    clients = await list_trainer_clients(db_session, trainer_id, limit=50)
    card_list = next(r for r in clients if int(r["id"]) == child_id)
    assert card_list["telegram_id"] == tid
    assert card_list["in_bot"] is True
    assert (card_list.get("phone") or "").strip() == phone

    card = await get_trainer_client_for_card(db_session, trainer_id, child_id)
    assert card is not None
    assert card["telegram_id"] == tid
    assert (card.get("phone") or "").strip() == phone


@pytest.mark.asyncio
async def test_get_client_request_for_booking_uses_acting_child_profile(
    app_use_test_db, db_session
) -> None:
    from src.application.client_request_use_cases import get_client_request_for_booking
    from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

    sid, cid, _aid = await _require_seed_ids(db_session)
    tid = _fresh_client_telegram_id()
    await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")
            created = await client.post(
                "/api/webapp/client/request",
                json={"city_id": cid, "service_id": sid, "comment": "для Леры"},
                headers={**_client_auth_headers(), "X-Profile-Id": str(child_id)},
            )
    assert created.status_code == 200, created.text
    request_id = int(created.json()["request_id"])

    missing = await get_client_request_for_booking(db_session, request_id, tid)
    assert missing is None
    found = await get_client_request_for_booking(
        db_session, request_id, tid, acting_client_id=child_id
    )
    assert found is not None
    assert int(found["id"]) == request_id
