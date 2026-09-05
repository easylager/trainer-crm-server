"""TASK-057: HTTP toggle for trainer_arenas.is_public + slot auto-link."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.application.test_trainer_arena_is_public import _foreign_city_arena, _two_same_city_arenas
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)
from tests.db_catalog_helpers import require_seed_service_id


@pytest.mark.asyncio
async def test_patch_arena_public_hides_from_catalog_filter(
    app_use_test_db,
    db_session,
) -> None:
    """AC-003: PATCH /trainer/arenas/{id}/public immediately changes public listing."""
    arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_a, "tid": trainer_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_a},
    )
    await db_session.execute(
        text("UPDATE trainers SET is_catalog_visible = true WHERE id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            shown = await client.get(
                "/api/public/trainers",
                params={"city_id": city_a, "arena_id": arena_a, "limit": 200},
            )
            assert shown.status_code == 200
            assert trainer_id in {t["id"] for t in shown.json()["items"]}

            hide = await client.patch(
                f"/api/webapp/trainer/arenas/{arena_a}/public",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"is_public": False},
            )
            assert hide.status_code == 200, hide.text
            body = hide.json()
            assert body["is_public"] is False
            flags = (body.get("trainer") or {}).get("arena_is_public") or {}
            assert flags.get(str(arena_a)) is False or flags.get(arena_a) is False

            hidden = await client.get(
                "/api/public/trainers",
                params={"city_id": city_a, "arena_id": arena_a, "limit": 200},
            )
            assert hidden.status_code == 200
            assert trainer_id not in {t["id"] for t in hidden.json()["items"]}

            show = await client.patch(
                f"/api/webapp/trainer/arenas/{arena_a}/public",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"is_public": True},
            )
            assert show.status_code == 200, show.text

            shown_again = await client.get(
                "/api/public/trainers",
                params={"city_id": city_a, "arena_id": arena_a, "limit": 200},
            )
            assert shown_again.status_code == 200
            assert trainer_id in {t["id"] for t in shown_again.json()["items"]}


@pytest.mark.asyncio
async def test_post_slots_unbound_same_city_auto_links_non_public(
    app_use_test_db,
    db_session,
) -> None:
    """AC-001 via HTTP: POST /schedule/slots on unbound same-city arena creates is_public=false."""
    arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_a, "tid": trainer_id},
    )
    await db_session.commit()

    d = date.today() + timedelta(days=42)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "capacity": 1,
                    "slot_entries": [
                        {"start_time": "10:00", "duration_minutes": 60, "arena_id": arena_a}
                    ],
                },
            )
    assert resp.status_code == 200, resp.text
    r = await db_session.execute(
        text(
            "SELECT is_public FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"
        ),
        {"tid": trainer_id, "aid": arena_a},
    )
    row = r.fetchone()
    assert row is not None
    assert bool(row[0]) is False


@pytest.mark.asyncio
async def test_post_slots_other_city_refuses_without_link(
    app_use_test_db,
    db_session,
) -> None:
    """AC-004 via HTTP: other-city arena → 400, no trainer_arenas row."""
    _arena_a, _arena_second, city_a = await _two_same_city_arenas(db_session)
    arena_b = await _foreign_city_arena(db_session, city_a)
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET city_id = :cid WHERE trainer_id = :tid"),
        {"cid": city_a, "tid": trainer_id},
    )
    await db_session.commit()

    d = date.today() + timedelta(days=43)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "capacity": 1,
                    "slot_entries": [
                        {"start_time": "10:00", "duration_minutes": 60, "arena_id": arena_b}
                    ],
                },
            )
    assert resp.status_code == 400
    r = await db_session.execute(
        text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
        {"tid": trainer_id, "aid": arena_b},
    )
    assert r.fetchone() is None
