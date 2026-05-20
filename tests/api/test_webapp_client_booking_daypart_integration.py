"""Integration: /client/slots filtered by per-trainer client daypart."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.client_booking_daypart_use_cases import (
    get_client_booking_daypart,
    set_client_booking_daypart,
)
from src.application.client_use_cases import get_or_create_client
from src.application.trainer_schedule_use_cases import replace_slots_for_day
from src.infrastructure.db.models import SUBSCRIPTION_TIER_ONLINE
from tests.api.test_webapp_client_miniapp_integration import (
    _create_trainer_online_with_slot,
    _ensure_trainer_subscription_tier,
    _minsk_monday_reference,
    patch_client_init_auth,
)


def _fresh_client_telegram_id() -> int:
    return 7_100_000_000 + (uuid.uuid4().int % 2_000_000_000)


@pytest.mark.asyncio
async def test_client_slots_filtered_by_morning_daypart(app_use_test_db, db_session: AsyncSession) -> None:
    ref_day, ref_now = _minsk_monday_reference()
    slot_day = ref_day + timedelta(days=3)
    trainer_id, _sid, _ = await _create_trainer_online_with_slot(
        db_session,
        slot_date=slot_day,
        start_hours={8, 10, 14, 18},
        tier=SUBSCRIPTION_TIER_ONLINE,
    )
    ctg = _fresh_client_telegram_id()
    client_id = await get_or_create_client(db_session, ctg)
    await set_client_booking_daypart(db_session, trainer_id, int(client_id), "morning")

    with patch_client_init_auth(ctg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with (
                patch("src.api.routes.webapp.get_slots_cached", return_value=None),
                patch("src.api.routes.webapp.datetime") as mock_dt,
                patch("src.api.routes.webapp.date") as mock_date,
            ):
                mock_date.today.return_value = ref_day
                mock_dt.now.return_value = ref_now
                mock_dt.combine = datetime.combine
                mock_dt.strftime = datetime.strftime
                resp = await client.get(
                    f"/api/webapp/client/slots?trainer_id={trainer_id}&min_hours=0",
                    headers={"X-Telegram-Init-Data": "mock"},
                )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("self_book_window") == "morning"
    starts = {s["start_time"] for s in data.get("slots") or []}
    assert starts <= {"08:00", "10:00"}
    assert "14:00" not in starts
    assert "18:00" not in starts


@pytest.mark.asyncio
async def test_patch_trainer_client_self_book_window(app_use_test_db, db_session: AsyncSession) -> None:
    from tests.api.test_webapp_trainer_client_identity import patch_trainer_webapp_init

    tg = 5_310_000_000 + (uuid.uuid4().int % 4_000_000_000)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": tg, "id": trainer_id},
    )
    r2 = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name)
            VALUES (700002, 'B') RETURNING id
            """
        )
    )
    client_id = int(r2.fetchone()[0])
    service_id = (
        await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    ).scalar()
    slot_day = date.today() + timedelta(days=10)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, :st, :en, 'booked', 1, :svc)
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_day,
            "st": time(10, 0),
            "en": time(11, 0),
            "svc": service_id,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, (SELECT id FROM slots WHERE trainer_id = :tid LIMIT 1), :svc, 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            resp = await http.patch(
                f"/api/webapp/trainer/clients/{client_id}/self-book-window",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"daypart": "evening"},
            )
    assert resp.status_code == 200
    win = resp.json().get("self_book_window") or {}
    assert win.get("value") == "evening"
    assert win.get("label") == "Вечер"

    loaded = await get_client_booking_daypart(db_session, trainer_id, client_id)
    assert loaded == "evening"
