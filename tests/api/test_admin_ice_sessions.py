"""TASK-050: admin ice session CRUD, week grid, recurrence (AC-001, AC-002, AC-005)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.deps import get_admin_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.arena_profile import backfill_arena_profiles


@contextmanager
def patch_admin_principal(user_id: int = 4242) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=user_id)
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


async def _insert_arena(db_session, *, country: str = "BY") -> tuple[int, int]:
    r = await db_session.execute(
        text("SELECT id FROM cities WHERE country = :c ORDER BY id LIMIT 1"),
        {"c": country},
    )
    cid = r.scalar()
    if cid is None:
        ins_city = await db_session.execute(
            text(
                """
                INSERT INTO cities (name, country, price_group, is_active)
                VALUES (:name, :c, :pg, true)
                RETURNING id
                """
            ),
            {
                "name": f"IceCity-{country}-{uuid.uuid4().hex[:6]}",
                "c": country,
                "pg": "BY_BASE" if country == "BY" else "RU_BASE",
            },
        )
        cid = int(ins_city.scalar_one())
    ins = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Ледовая, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": cid, "name": f"Лёд {uuid.uuid4().hex[:8]}"},
    )
    arena_id = int(ins.scalar_one())
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    return int(cid), arena_id


def _payload(**overrides):
    body = {
        "local_date": "2026-09-07",
        "starts_at_local": "11:00",
        "duration_minutes": 45,
        "kind": "public_skate",
        "price_adult_minor": 850,
        "price_child_minor": 600,
        "price_rental_minor": 1200,
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_admin_create_session_appears_in_week_grid(app_use_test_db, db_session) -> None:
    """AC-001: create a slot and see it in that arena's week grid."""
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(),
            )
            assert created.status_code == 200, created.text
            body = created.json()
            assert body["kind"] == "public_skate"
            assert body["starts_at_local"] == "11:00"
            assert body["ends_at_local"] == "11:45"
            assert body["price_adult_minor"] == 850
            assert body["price_child_minor"] == 600
            assert body["price_rental_minor"] == 1200
            assert body["price_minor"] == 600
            assert body["currency_code"] == "BYN"
            assert body["starts_at_utc"].startswith("2026-09-07T08:00:00")
            session_id = body["id"]

            grid = await client.get(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                params={"week_start": "2026-09-07"},
            )
    assert grid.status_code == 200, grid.text
    data = grid.json()
    assert data["week_start"] == "2026-09-07"
    assert data["timezone"] == "Europe/Minsk"
    assert data["currency_code"] == "BYN"
    assert len(data["days"]) == 7
    monday = next(d for d in data["days"] if d["local_date"] == "2026-09-07")
    ids = [s["id"] for s in monday["sessions"]]
    assert session_id in ids
    slot = next(s for s in monday["sessions"] if s["id"] == session_id)
    assert slot["starts_at_local"] == "11:00"


@pytest.mark.asyncio
async def test_admin_edit_and_delete_session(app_use_test_db, db_session) -> None:
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(),
            )
            session_id = created.json()["id"]
            patched = await client.patch(
                f"/api/webapp/admin/ice-sessions/{session_id}",
                json={"starts_at_local": "12:00", "duration_minutes": 60},
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["starts_at_local"] == "12:00"
            assert patched.json()["ends_at_local"] == "13:00"
            deleted = await client.delete(f"/api/webapp/admin/ice-sessions/{session_id}")
            assert deleted.status_code == 200, deleted.text
            grid = await client.get(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                params={"week_start": "2026-09-07"},
            )
    days = grid.json()["days"]
    monday = next(d for d in days if d["local_date"] == "2026-09-07")
    assert all(s["id"] != session_id for s in monday["sessions"])


@pytest.mark.asyncio
async def test_copy_week_duplicates_sessions_to_next_week(app_use_test_db, db_session) -> None:
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(),
            )
            copied = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions/copy-week",
                json={"from_week_start": "2026-09-07"},
            )
            assert copied.status_code == 200, copied.text
            assert copied.json()["copied"] >= 1
            next_week = await client.get(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                params={"week_start": "2026-09-14"},
            )
    monday = next(d for d in next_week.json()["days"] if d["local_date"] == "2026-09-14")
    assert any(s["starts_at_local"] == "11:00" and s["kind"] == "public_skate" for s in monday["sessions"])


@pytest.mark.asyncio
async def test_recurrence_cancel_does_not_resurrect_on_rematerialize(app_use_test_db, db_session) -> None:
    """AC-002: cancelling one instance keeps it cancelled after rematerialize."""
    _cid, arena_id = await _insert_arena(db_session)
    start = date(2026, 9, 5)  # Saturday
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(local_date=start.isoformat(), repeat_weekly=True),
            )
            assert created.status_code == 200, created.text
            key = created.json()["recurrence_key"]
            assert key
            first_id = created.json()["id"]

            cancelled = await client.delete(f"/api/webapp/admin/ice-sessions/{first_id}")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json().get("status") == "cancelled"

            remat = await client.post(
                f"/api/webapp/admin/ice-sessions/recurrence/{key}/rematerialize",
            )
            assert remat.status_code == 200, remat.text

            week = (start - timedelta(days=start.weekday())).isoformat()
            grid = await client.get(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                params={"week_start": week, "include_cancelled": True},
            )
            later = await client.get(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                params={"week_start": (start - timedelta(days=start.weekday()) + timedelta(days=7)).isoformat()},
            )
    sat = next(d for d in grid.json()["days"] if d["local_date"] == start.isoformat())
    first = next(s for s in sat["sessions"] if s["id"] == first_id)
    assert first["status"] == "cancelled"
    next_sat = next(
        d for d in later.json()["days"] if d["local_date"] == (start + timedelta(days=7)).isoformat()
    )
    assert any(
        s["recurrence_key"] == key and s["status"] == "active" for s in next_sat["sessions"]
    )


@pytest.mark.asyncio
async def test_overlap_and_short_duration_return_clear_errors(app_use_test_db, db_session) -> None:
    """AC-005: overlap and 15-minute duration are rejected with a readable error."""
    _cid, arena_id = await _insert_arena(db_session)
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            ok = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(),
            )
            assert ok.status_code == 200, ok.text
            overlap = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(starts_at_local="11:15", duration_minutes=45),
            )
            short = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(starts_at_local="18:00", duration_minutes=15),
            )
    assert overlap.status_code == 400
    assert "пересек" in overlap.json()["detail"].lower()
    assert short.status_code == 400
    assert "30" in short.json()["detail"] and "120" in short.json()["detail"]


@pytest.mark.asyncio
async def test_rub_city_session_keeps_rub_currency(app_use_test_db, db_session) -> None:
    """AC-004: currency comes from the city, not a free-typed string."""
    _cid, arena_id = await _insert_arena(db_session, country="RU")
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json=_payload(price_adult_minor=40000, price_child_minor=None, price_rental_minor=None),
            )
    assert created.status_code == 200, created.text
    assert created.json()["currency_code"] == "RUB"
    assert created.json()["price_minor"] == 40000


def test_admin_dicts_has_ice_week_grid() -> None:
    html = Path("static/webapp/admin-dicts.html").read_text(encoding="utf-8")
    assert "ice-sessions" in html
    assert "ice-week" in html
