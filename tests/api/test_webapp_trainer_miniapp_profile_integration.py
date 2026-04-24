"""
Integration tests for the trainer Mini App «Профиль» (trainer-profile.html) API surface.

Covers: GET/PATCH /api/webapp/trainer/profile, education CRUD, photo presign/register/upload,
GET/POST onboarding moderation endpoints used by the same page.

Assertions are behavior-oriented (payload shape, consistency between endpoints, isolation, validation)
so regressions surface as failures rather than weak «status code only» checks.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta, time
from io import BytesIO
from urllib.parse import quote
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import text

from src.api.app import app
from src.shared.telegram_webapp import InitDataAuthError


def _fresh_trainer_telegram_id() -> int:
    return 5_000_000_000 + (uuid.uuid4().int % 4_000_000_000)


def _tiny_jpeg_bytes() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (8, 8), color=(90, 120, 200)).save(buf, "JPEG", quality=80)
    return buf.getvalue()


@contextmanager
def patch_trainer_init_auth(telegram_id: int) -> Iterator[None]:
    """Both profile routes and webapp.onboarding use trainer-bot initData validation."""
    with (
        patch("src.api.routes.webapp_trainer_profile.require_telegram_user_id", return_value=telegram_id),
        patch("src.api.routes.webapp.require_telegram_user_id", return_value=telegram_id),
    ):
        yield


@pytest.mark.asyncio
async def test_get_profile_via_init_data_query_matches_header(
    app_use_test_db,
    db_session,
) -> None:
    """Mini App may send init_data as query param; response must match header auth path."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Q", "last_name": "Param", "age": 31}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            via_header = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            q = quote("mock", safe="")
            via_query = await client.get(f"/api/webapp/trainer/profile?init_data={q}")
    assert via_header.status_code == 200
    assert via_query.status_code == 200
    assert via_header.json() == via_query.json()


@pytest.mark.asyncio
async def test_moderation_readiness_matches_between_profile_and_onboarding_endpoint(
    app_use_test_db,
    db_session,
) -> None:
    """Single source of truth: embedded moderation_readiness must equal dedicated GET."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Согл", "last_name": "Тест", "age": 29}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            ready = await client.get(
                "/api/webapp/trainer/onboarding/moderation-readiness",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert prof.status_code == 200
    assert ready.status_code == 200
    embedded = prof.json().get("moderation_readiness")
    standalone = ready.json()
    assert embedded == standalone
    for key in (
        "complete",
        "missing_fields",
        "missing_labels_ru",
        "trainer_status",
        "already_submitted_for_moderation",
        "moderation_criteria_total",
        "full_profile_complete",
        "full_profile_missing_fields",
        "full_profile_missing_labels_ru",
        "full_profile_criteria_total",
        "tt_minimal_complete",
        "tt_minimal_missing_fields",
        "tt_minimal_missing_labels_ru",
        "tt_minimal_criteria_total",
    ):
        assert key in standalone
    assert standalone.get("moderation_criteria_total") == 8
    assert standalone.get("full_profile_criteria_total") == 12


@pytest.mark.asyncio
async def test_onboarding_checklist_inactive_trainer_slots_and_bookings_locked(
    app_use_test_db,
    db_session,
) -> None:
    """Before activation, slot/booking flags are false and steps are explicitly locked."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Чек", "last_name": "Лист", "age": 28}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("is_active") is False
    assert data.get("is_catalog_visible") is True
    assert "full_profile_complete" in data
    assert data.get("slots_this_week_count") == 0
    assert data.get("slots_next_week_count") == 0
    assert data.get("available_slots_this_week_count") == 0
    assert data.get("available_slots_next_week_count") == 0
    assert data.get("bookings_this_week_count") == 0
    assert data.get("bookings_next_week_count") == 0
    assert data.get("has_future_available_slots") is False
    assert data.get("has_future_slots") is False
    assert data.get("has_any_booking") is False
    assert data.get("has_upcoming_booking") is False
    assert data.get("weekly_template_count") == 0
    assert data.get("slots_locked_reason")
    assert data.get("bookings_locked_reason")
    assert data.get("schedule_unlocked") is False
    assert data.get("fill_slots_invite_candidates_count") == 0


@pytest.mark.asyncio
async def test_onboarding_checklist_active_future_available_slot(
    app_use_test_db,
    db_session,
) -> None:
    """Active trainer: has_future_available_slots follows DB (empty vs one future slot)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Слот', 'Тест', 29)"
        ),
        {"tid": tid},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            empty = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert empty.status_code == 200
    ej = empty.json()
    assert ej.get("is_active") is True
    assert ej.get("schedule_unlocked") is True
    assert ej.get("weekly_template_count") == 0
    assert ej.get("slots_this_week_count") == 0
    assert ej.get("slots_next_week_count") == 0
    assert ej.get("available_slots_this_week_count") == 0
    assert ej.get("available_slots_next_week_count") == 0
    assert ej.get("bookings_this_week_count") == 0
    assert ej.get("bookings_next_week_count") == 0
    assert ej.get("slots_locked_reason") is None
    assert ej.get("has_future_available_slots") is False
    assert ej.get("has_future_slots") is False
    assert ej.get("has_upcoming_booking") is False

    slot_day = date.today() + timedelta(days=14)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :en, 'available')
            """
        ),
        {"tid": tid, "d": slot_day, "st": time(10, 0), "en": time(11, 0)},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            filled = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert filled.status_code == 200
    fj = filled.json()
    assert fj.get("has_future_available_slots") is True
    assert fj.get("has_future_slots") is True
    assert fj.get("has_upcoming_booking") is False


@pytest.mark.asyncio
async def test_onboarding_checklist_booked_future_slot_counts_for_slots_step(
    app_use_test_db,
    db_session,
) -> None:
    """Future slot fully booked: has_future_slots true, has_future_available_slots false (onboarding step 2 done)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Бронь', 'Слот', 30)"
        ),
        {"tid": tid},
    )
    slot_day = date.today() + timedelta(days=7)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :en, 'booked')
            """
        ),
        {"tid": tid, "d": slot_day, "st": time(14, 0), "en": time(15, 0)},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("has_future_available_slots") is False
    assert data.get("has_future_slots") is True
    assert data.get("has_upcoming_booking") is False


@pytest.mark.asyncio
async def test_onboarding_checklist_week_slot_counters(
    app_use_test_db,
    db_session,
) -> None:
    """Checklist returns separate slot counters for this week (from today) and next week."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Неделя', 'Счётчик', 30)"
        ),
        {"tid": tid},
    )
    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()))
    next_week_start = week_end + timedelta(days=1)
    next_week_day = next_week_start + timedelta(days=1)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES
              (:tid, :d_this, TIME '10:00', TIME '11:00', 'available'),
              (:tid, :d_next, TIME '12:00', TIME '13:00', 'booked')
            """
        ),
        {"tid": tid, "d_this": today, "d_next": next_week_day},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("slots_this_week_count") == 1
    assert data.get("slots_next_week_count") == 1
    assert data.get("available_slots_this_week_count") == 1
    assert data.get("available_slots_next_week_count") == 0
    assert data.get("bookings_this_week_count") == 0
    assert data.get("bookings_next_week_count") == 0


@pytest.mark.asyncio
async def test_onboarding_checklist_bookings_this_week_count(
    app_use_test_db,
    db_session,
) -> None:
    """bookings_this_week_count counts non-cancelled bookings in the current week window."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Букинг', 'Неделя', 31)"
        ),
        {"tid": tid},
    )
    svc_name = "Test service " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    r_client = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'Клиент') RETURNING id"),
        {"tg": _fresh_trainer_telegram_id()},
    )
    client_id = r_client.fetchone()[0]
    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()))
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": today},
    )
    slot_id = r_slot.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_id, "tid": tid, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("bookings_this_week_count") == 1
    assert data.get("bookings_next_week_count") == 0


@pytest.mark.asyncio
async def test_onboarding_checklist_has_upcoming_booking_uses_hub_upcoming_filter(
    app_use_test_db,
    db_session,
) -> None:
    """Upcoming booking flag should match hub list logic (pending/confirmed + slot end in future)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Апкоминг', 'Чеклист', 31)"
        ),
        {"tid": tid},
    )
    svc_name = "Test service " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    r_client = await db_session.execute(
        text(
            "INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'Клиент') RETURNING id"
        ),
        {"tg": _fresh_trainer_telegram_id()},
    )
    client_id = r_client.fetchone()[0]
    slot_day = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :en, 'available')
            RETURNING id
            """
        ),
        {"tid": tid, "d": slot_day, "st": time(10, 0), "en": time(11, 0)},
    )
    slot_id = r_slot.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'pending')
            """
        ),
        {"sid": slot_id, "tid": tid, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("has_upcoming_booking") is True

    await db_session.execute(
        text("UPDATE slots SET slot_date = :d WHERE id = :sid"),
        {"d": date.today() - timedelta(days=1), "sid": slot_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp2 = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2.get("has_upcoming_booking") is False


@pytest.mark.asyncio
async def test_onboarding_checklist_completed_booking_and_last_client_id(
    app_use_test_db,
    db_session,
) -> None:
    """Hub rhythm strip: has_completed_booking + last_completed_booking_client_id (ORDER BY booking id)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Доне', 'Чеклист', 31)"
        ),
        {"tid": tid},
    )
    svc_name = "Test service " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    r_c1 = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'A') RETURNING id"),
        {"tg": _fresh_trainer_telegram_id()},
    )
    client_a = r_c1.fetchone()[0]
    r_c2 = await db_session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'B') RETURNING id"),
        {"tg": _fresh_trainer_telegram_id()},
    )
    client_b = r_c2.fetchone()[0]
    slot_day = date.today() + timedelta(days=3)
    r_slot_a = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": slot_day},
    )
    slot_a = r_slot_a.fetchone()[0]
    r_slot_b = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '12:00', TIME '13:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": slot_day},
    )
    slot_b = r_slot_b.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_a, "tid": tid, "cid": client_a, "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_b, "tid": tid, "cid": client_b, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("has_completed_booking") is True
    assert data.get("last_completed_booking_client_id") == int(client_b)


@pytest.mark.asyncio
async def test_get_profile_trainer_aggregate_shape_for_ui(
    app_use_test_db,
    db_session,
) -> None:
    """Contract for client: keys the Mini App relies on must be present with expected types."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Форма", "last_name": "Ключей", "age": 32}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    payload = resp.json()
    t = payload["trainer"]
    assert t["id"] == trainer_id
    assert isinstance(t.get("profile"), dict)
    assert isinstance(t.get("photos"), list)
    assert isinstance(t.get("service_ids"), list)
    assert isinstance(t.get("arena_ids"), list)
    assert "status" in t
    assert isinstance(payload.get("education_entries"), list)


@pytest.mark.asyncio
async def test_get_profile_401_when_init_data_invalid(
    app_use_test_db,
) -> None:
    def _raise_invalid(*_a, **_kw) -> int:
        raise InitDataAuthError("bad signature")

    with patch("src.api.routes.webapp_trainer_profile.require_telegram_user_id", side_effect=_raise_invalid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "garbage"},
            )
    assert resp.status_code == 401
    assert "init" in (resp.json().get("detail") or "").lower()


@pytest.mark.asyncio
async def test_patch_profile_empty_body_still_ok(
    app_use_test_db,
    db_session,
) -> None:
    """No-op PATCH should succeed so the client can send minimal payloads."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Пуст", "last_name": "Патч", "age": 40}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={},
            )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_patch_profile_services_payload_updates_list_and_prices(
    app_use_test_db,
    db_session,
) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    if sid is None:
        pytest.skip("need at least one service in DB")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Усл", "last_name": "Цена", "age": 35}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch_resp = await client.patch(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"services": [{"service_id": sid, "price_byn": 12.5}]},
            )
            get_resp = await client.get(f"/api/trainers/{trainer_id}")
    assert patch_resp.status_code == 200
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert sid in (body.get("service_ids") or [])
    services = body.get("services") or []
    match = next((s for s in services if s.get("service_id") == sid), None)
    assert match is not None
    assert match.get("price_byn") == 12.5


@pytest.mark.asyncio
async def test_education_entries_count_matches_list_length(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Эд", "last_name": "Счёт", "age": 28}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            post_resp = await client.post(
                "/api/webapp/trainer/education",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "education_type": "course_or_certificate",
                    "institution_name": "Институт",
                    "program_or_title": "Курс повышения квалификации",
                },
            )
            assert post_resp.status_code == 201
            prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert prof.status_code == 200
    data = prof.json()
    entries = data["education_entries"]
    cnt = data["trainer"].get("education_entries_count")
    if cnt is not None:
        assert int(cnt) == len(entries)
    assert len(entries) >= 1
    row = entries[0]
    for k in ("id", "education_type", "institution_name", "program_or_title", "moderation_status"):
        assert k in row


@pytest.mark.asyncio
async def test_education_post_422_when_institution_too_short(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Вал", "last_name": "Ошибка", "age": 30}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/education",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "education_type": "formal_education",
                    "institution_name": "Я",
                    "program_or_title": "Коротко",
                },
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_education_cannot_patch_other_trainers_entry(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        a = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "А", "last_name": "Один", "age": 30}},
        )
        b = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Б", "last_name": "Два", "age": 31}},
        )
        id_a = a.json()["id"]
        _id_b = b.json()["id"]
    tg_a = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg_a, "id": id_a},
    )
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        other = await client.post(
            f"/api/trainers/{_id_b}/education",
            json={
                "education_type": "formal_education",
                "institution_name": "Чужая запись",
                "program_or_title": "Программа чужого тренера",
            },
        )
    assert other.status_code == 201
    foreign_edu_id = other.json()["id"]

    with patch_trainer_init_auth(tg_a):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/webapp/trainer/education/{foreign_edu_id}",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"program_or_title": "Взлом через вебапп"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_education_delete_unknown_id_404(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Уд", "last_name": "Нет", "age": 33}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                "/api/webapp/trainer/education/999999999",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404
    assert resp.json().get("detail") == "Education entry not found"


@pytest.mark.asyncio
async def test_photo_presign_returns_upload_url_and_scoped_file_key(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Ф", "last_name": "Пресайн", "age": 36}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    fake_url = "https://bucket.example/presigned-put"
    fake_key = f"trainers/{trainer_id}/deadbeef.jpg"

    with patch_trainer_init_auth(tg):
        with patch(
            "src.api.routes.webapp_trainer_profile.s3.presign_upload_url",
            return_value=(fake_url, fake_key),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/webapp/trainer/photos/presign",
                    headers={"X-Telegram-Init-Data": "mock"},
                    json={"content_type": "image/jpeg"},
                )
    assert resp.status_code == 200
    data = resp.json()
    assert data["upload_url"] == fake_url
    assert data["file_key"] == fake_key
    assert data["file_key"].startswith(f"trainers/{trainer_id}/")


@pytest.mark.asyncio
async def test_photo_register_403_when_file_key_not_under_trainer_prefix(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "ИДОР", "last_name": "Ключ", "age": 37}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/photos/register",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"file_key": "trainers/99999999/evil.jpg"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_photo_register_success_with_valid_key(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Ок", "last_name": "Фото", "age": 38}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()
    fk = f"trainers/{trainer_id}/integration-reg.jpg"

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/photos/register",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"file_key": fk},
            )
            get_p = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"file_key": fk}
    assert get_p.status_code == 200
    photos = get_p.json()["trainer"].get("photos") or []
    assert any(p.get("file_key") == fk for p in photos)


@pytest.mark.asyncio
async def test_photo_multipart_upload_rejects_non_image(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Бит", "last_name": "Мап", "age": 39}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/photos",
                headers={"X-Telegram-Init-Data": "mock"},
                files={"file": ("x.jpg", b"not an image at all", "image/jpeg")},
            )
    assert resp.status_code == 400
    assert resp.json().get("detail") == "Not a valid image"


@pytest.mark.asyncio
async def test_photo_multipart_upload_accepts_tiny_jpeg(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Дж", "last_name": "Пег", "age": 34}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()
    body = _tiny_jpeg_bytes()

    def _fake_upload_photo(tid: int, _body: bytes, _content_type: str) -> tuple[str, None]:
        """CI has no S3/local storage; assert API + DB path, not object storage."""
        return (f"trainers/{tid}/ci-test.jpg", None)

    with patch_trainer_init_auth(tg):
        with patch(
            "src.application.trainer_use_cases.s3.upload_photo",
            side_effect=_fake_upload_photo,
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.post(
                    "/api/webapp/trainer/photos",
                    headers={"X-Telegram-Init-Data": "mock"},
                    files={"file": ("tiny.jpg", body, "image/jpeg")},
                )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("file_key")
    assert str(data["file_key"]).startswith(f"trainers/{trainer_id}/")


@pytest.mark.asyncio
async def test_submit_for_moderation_incomplete_returns_422_with_missing_fields(
    app_use_test_db,
    db_session,
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={"profile": {"first_name": "Неп", "last_name": "Полон", "age": 27}},
        )
        trainer_id = create_resp.json()["id"]
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/onboarding/submit-for-moderation",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 422
    detail = resp.json().get("detail")
    assert isinstance(detail, dict)
    assert "missing_fields" in detail
    assert "missing_labels_ru" in detail
    assert isinstance(detail["missing_fields"], list)
    assert len(detail["missing_fields"]) > 0


@pytest.mark.asyncio
async def test_submit_for_moderation_success_when_profile_complete(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    r3 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r3.scalar()
    if sid is None or cid is None or aid is None:
        pytest.skip("need seed services, cities, and arenas")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={
                "profile": {
                    "first_name": "Полный",
                    "last_name": "Профиль",
                    "age": 26,
                    "phone": "+375291112233",
                    "description": "x" * 30,
                    "city_id": cid,
                    "education": "Высшее профильное",
                    "experience_years": 2,
                    "session_duration_minutes": 60,
                    "min_hours_before_booking": 12,
                },
                "service_ids": [sid],
                "arena_ids": [aid],
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
    await db_session.execute(
        text(
            "INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :fk, 0)"
        ),
        {"tid": trainer_id, "fk": f"trainers/{trainer_id}/mod.jpg"},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    notified: list[int] = []

    async def fake_notify(tid: int) -> None:
        notified.append(tid)

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        fake_notify,
    )

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/onboarding/submit-for-moderation",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json().get("submitted") is True
    assert notified == [trainer_id]


@pytest.mark.asyncio
async def test_submit_for_moderation_succeeds_with_submission_tier_only_profile(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    """Bio block optional for queue: no age/description/education/experience when core 8 are set."""
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    r3 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r3.scalar()
    if sid is None or cid is None or aid is None:
        pytest.skip("need seed services, cities, and arenas")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={
                "profile": {
                    "first_name": "Короткий",
                    "last_name": "Путь",
                    "age": 0,
                    "phone": "+375291112233",
                    "city_id": cid,
                    "session_duration_minutes": 60,
                },
                "service_ids": [sid],
                "arena_ids": [aid],
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
    await db_session.execute(
        text(
            "INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :fk, 0)"
        ),
        {"tid": trainer_id, "fk": f"trainers/{trainer_id}/thin.jpg"},
    )
    await db_session.execute(
        text(
            "UPDATE trainer_profiles SET min_hours_before_booking = 12 "
            "WHERE trainer_id = :tid"
        ),
        {"tid": trainer_id},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        lambda _tid: None,
    )

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            prof = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            mr = prof.json()["moderation_readiness"]
            assert mr["complete"] is True
            assert mr["full_profile_complete"] is False
            resp = await client.post(
                "/api/webapp/trainer/onboarding/submit-for-moderation",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json().get("submitted") is True


@pytest.mark.asyncio
async def test_moderation_readiness_embedded_reflects_submit_state(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    """After successful submit, already_submitted_for_moderation should be true when rules say so."""
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    r3 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r3.scalar()
    if sid is None or cid is None or aid is None:
        pytest.skip("need seed services, cities, and arenas")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_resp = await client.post(
            "/api/trainers",
            json={
                "profile": {
                    "first_name": "Флаг",
                    "last_name": "Модерации",
                    "age": 28,
                    "phone": "+375291112233",
                    "description": "y" * 30,
                    "city_id": cid,
                    "education": "Курсы и сертификация",
                    "experience_years": 1,
                    "session_duration_minutes": 45,
                    "min_hours_before_booking": 6,
                },
                "service_ids": [sid],
                "arena_ids": [aid],
            },
        )
        assert create_resp.status_code == 200, create_resp.text
        trainer_id = create_resp.json()["id"]
    await db_session.execute(
        text(
            "INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:tid, :fk, 0)"
        ),
        {"tid": trainer_id, "fk": f"trainers/{trainer_id}/flag.jpg"},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    await db_session.commit()

    monkeypatch.setattr(
        "src.application.trainer_use_cases.notify_admins_trainer_queued_for_moderation",
        lambda _tid: None,
    )

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            before = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert before.json()["moderation_readiness"]["complete"] is True
            assert before.json()["moderation_readiness"]["already_submitted_for_moderation"] is False
            sub = await client.post(
                "/api/webapp/trainer/onboarding/submit-for-moderation",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert sub.status_code == 200
            after = await client.get(
                "/api/webapp/trainer/profile",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    mr = after.json()["moderation_readiness"]
    assert mr["already_submitted_for_moderation"] is True


@pytest.mark.asyncio
async def test_onboarding_checklist_open_loop_aggregates(
    app_use_test_db,
    db_session,
) -> None:
    """Hub rhythm: open_loop_* counts for pending, no-upcoming, no-telegram (trainer_onboarding_checklist)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Open', 'Loop', 30)"
        ),
        {"tid": tid},
    )
    svc_name = "Oloop svc " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": tid, "sid": service_id},
    )
    p_a, pn_a = "+37544" + str(800_000 + (uuid.uuid4().int % 9_000)), "37544" + str(800_000 + (uuid.uuid4().int % 9_000))
    p_b, pn_b = "+37544" + str(900_000 + (uuid.uuid4().int % 9_000)), "37544" + str(900_000 + (uuid.uuid4().int % 9_000))
    r_a = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (NULL, 'NoTg', :phone, :pn)
            RETURNING id
            """
        ),
        {"phone": p_a, "pn": pn_a},
    )
    client_a = r_a.fetchone()[0]
    r_b = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (:tg, 'Pending', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": _fresh_trainer_telegram_id(), "phone": p_b, "pn": pn_b},
    )
    client_b = r_b.fetchone()[0]
    past = date.today() - timedelta(days=2)
    future = date.today() + timedelta(days=3)
    r_past = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": past},
    )
    slot_past = r_past.fetchone()[0]
    r_future = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '12:00', TIME '13:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": future},
    )
    slot_future = r_future.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_past, "tid": tid, "cid": client_a, "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, notified_at)
            VALUES (:sid, :tid, :cid, :svc, 'pending', NOW())
            """
        ),
        {"sid": slot_future, "tid": tid, "cid": client_b, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("open_loop_pending_bookings_count") == 1
    assert data.get("open_loop_clients_no_upcoming_count") == 1
    assert data.get("open_loop_clients_no_telegram_count") == 1
    assert data.get("fill_slots_invite_candidates_count") == 0


@pytest.mark.asyncio
async def test_trainer_hub_fill_slots_invites_prefers_clients_without_upcoming(
    app_use_test_db,
    db_session,
) -> None:
    """GET /trainer/hub/fill-slots-invites ranks clients without a future session first."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Fill', 'Slots', 30)"
        ),
        {"tid": tid},
    )
    svc_name = "FillSlots " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": tid, "sid": service_id},
    )
    r_stale = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, telegram_username, first_name, phone, phone_normalized)
            VALUES (:tg, 'stale_user', 'Stale', '+37500000001', '37500000001')
            RETURNING id
            """
        ),
        {"tg": _fresh_trainer_telegram_id()},
    )
    stale_id = r_stale.fetchone()[0]
    r_hot = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, telegram_username, first_name, phone, phone_normalized)
            VALUES (:tg, 'hot_user', 'Hot', '+37500000002', '37500000002')
            RETURNING id
            """
        ),
        {"tg": _fresh_trainer_telegram_id()},
    )
    hot_id = r_hot.fetchone()[0]
    past = date.today() - timedelta(days=10)
    future = date.today() + timedelta(days=5)
    r_past = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": past},
    )
    slot_past = r_past.fetchone()[0]
    r_future = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '12:00', TIME '13:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": future},
    )
    slot_future = r_future.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_past, "tid": tid, "cid": stale_id, "svc": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, notified_at)
            VALUES (:sid, :tid, :cid, :svc, 'pending', NOW())
            """
        ),
        {"sid": slot_future, "tid": tid, "cid": hot_id, "svc": service_id},
    )
    r_skip = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (NULL, 'NoTgHub', '+37500000999', '37500000999')
            RETURNING id
            """
        ),
    )
    skip_id = r_skip.fetchone()[0]
    r_slot2 = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '14:00', TIME '15:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": past},
    )
    slot_past2 = r_slot2.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_past2, "tid": tid, "cid": skip_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/fill-slots-invites",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    payload = resp.json()
    clients = payload.get("clients") or []
    assert len(clients) == 1
    assert skip_id not in {c["id"] for c in clients}
    assert all(c.get("has_telegram") is True for c in clients)
    assert clients[0]["id"] == stale_id
    assert clients[0].get("has_upcoming_booking") is False
    assert "reason_line" in clients[0]

    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            chk = await client.get(
                "/api/webapp/trainer/onboarding/checklist",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert chk.status_code == 200
    assert chk.json().get("fill_slots_invite_candidates_count") == 1


@pytest.mark.asyncio
async def test_trainer_hub_fill_slots_invites_send_posts_to_client_bot(
    app_use_test_db,
    db_session,
) -> None:
    """POST fill-slots-invites/send delivers client-bot messages (Bot API mocked)."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = r.fetchone()[0]
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": tid},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Send', 'Test', 30)"
        ),
        {"tid": tid},
    )
    svc_name = "SendInv " + uuid.uuid4().hex[:8]
    r_service = await db_session.execute(
        text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
        {"name": svc_name},
    )
    service_id = r_service.fetchone()[0]
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": tid, "sid": service_id},
    )
    client_tg = _fresh_trainer_telegram_id()
    r_c = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (:tg, 'Notifier', '+37500000003', '37500000003')
            RETURNING id
            """
        ),
        {"tg": client_tg},
    )
    client_id = r_c.fetchone()[0]
    past = date.today() - timedelta(days=3)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, TIME '10:00', TIME '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": tid, "d": past},
    )
    slot_id = r_slot.fetchone()[0]
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'completed')
            """
        ),
        {"sid": slot_id, "tid": tid, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    mock_send = AsyncMock()
    with patch_trainer_init_auth(tg):
        with patch("src.application.trainer_fill_slots_invite_send.Settings") as MS:
            MS.return_value.webapp_base_url = "https://example.test"
            MS.return_value.telegram_bot_token_client = "dummy"
            with patch("src.application.trainer_fill_slots_invite_send.trainer_allows_online_booking", new=AsyncMock(return_value=True)):
                with patch("src.application.trainer_fill_slots_invite_send.Bot") as MockBot:
                    inst = MockBot.return_value
                    inst.send_message = mock_send
                    inst.session = AsyncMock()
                    inst.session.close = AsyncMock()
                    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                        resp = await client.post(
                            "/api/webapp/trainer/hub/fill-slots-invites/send",
                            headers={"X-Telegram-Init-Data": "mock"},
                            json={"client_ids": [client_id]},
                        )
    assert resp.status_code == 200
    body = resp.json()
    assert client_id in body.get("sent", [])
    mock_send.assert_awaited_once()
    call_kw = mock_send.await_args.kwargs
    assert int(call_kw["chat_id"]) == int(client_tg)
    assert "reply_markup" in call_kw
