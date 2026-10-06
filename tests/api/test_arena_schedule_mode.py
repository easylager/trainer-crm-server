"""TASK-204: arena schedule_mode on public API, SSR, admin, ice day."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.ice_city_day import get_city_ice_day
from src.application.place_page import _schedule_html, load_place_view
from src.shared.arena_schedule_mode import PHONE_LINE, SEASON_CLOSED_LINE
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_city


async def _set_mode(
    db_session,
    arena_id: int,
    *,
    mode: str,
    reopen: date | None = None,
    note: str | None = None,
) -> None:
    await db_session.execute(
        text(
            """
            UPDATE arena_profiles
            SET schedule_mode = :mode, reopen_date = :reopen, schedule_mode_note = :note
            WHERE arena_id = :id
            """
        ),
        {"id": arena_id, "mode": mode, "reopen": reopen, "note": note},
    )


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_public_list_exposes_schedule_mode(app_use_test_db, db_session, client) -> None:
    cid = await _insert_city(db_session, name=f"Mode-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Телефонный каток", phone="+375291112233")
    await _set_mode(db_session, arena_id, mode="phone")
    await db_session.commit()

    r = await client.get(f"/api/public/ice/arenas?city_id={cid}&intent=skate")
    assert r.status_code == 200
    item = next(x for x in r.json()["items"] if x["id"] == arena_id)
    assert item["schedule_mode"] == "phone"
    assert item["live"]["kind"] == "phone"
    assert item["live"]["text"] == PHONE_LINE


@pytest.mark.asyncio
async def test_season_closed_excluded_from_ice_day(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Day-{uuid.uuid4().hex[:6]}")
    open_arena = await _insert_arena(db_session, cid, name="Открытый")
    closed_arena = await _insert_arena(db_session, cid, name="Закрытый сезон")
    await _set_mode(db_session, closed_arena, mode="season_closed", note="ремонт")
    target = date.today() + timedelta(days=1)
    await _add_future_session(db_session, open_arena, days_ahead=1, starts_at_local="19:00")
    await _add_future_session(db_session, closed_arena, days_ahead=1, starts_at_local="18:00")
    await db_session.commit()

    now = datetime.now(timezone.utc)
    day = await get_city_ice_day(db_session, city_id=cid, on_date=target, now=now)
    arena_ids = {a["arena_id"] for a in day.get("arenas") or []}
    assert open_arena in arena_ids
    assert closed_arena not in arena_ids


@pytest.mark.asyncio
async def test_place_page_phone_mode_ssr(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Place-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="По телефону", phone="+375291112233")
    await _set_mode(db_session, arena_id, mode="phone")
    await db_session.commit()

    view = await load_place_view(db_session, str(arena_id))
    assert view is not None
    html = _schedule_html(view, base_path=f"/p/{arena_id}", invite=False)
    assert PHONE_LINE in html
    assert "tel:+375291112233" in html


@pytest.mark.asyncio
async def test_place_page_season_closed_ssr(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Closed-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Каток Жодино закрыт")
    await _set_mode(
        db_session,
        arena_id,
        mode="season_closed",
        reopen=date(2026, 11, 1),
        note="ремонт",
    )
    await db_session.commit()

    view = await load_place_view(db_session, str(arena_id))
    html = _schedule_html(view, base_path=f"/p/{arena_id}", invite=False)
    assert SEASON_CLOSED_LINE in html
    assert "откроется 01.11" in html
    assert "ремонт" in html


@pytest.mark.asyncio
async def test_admin_patch_schedule_mode(app_use_test_db, db_session) -> None:
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    cid = await _insert_city(db_session, name=f"Admin-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Админ режим")
    await db_session.commit()

    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bad = await client.patch(
            f"/api/webapp/admin/arenas/{arena_id}",
            json={"schedule_mode": "nope"},
        )
        assert bad.status_code == 400
        ok = await client.patch(
            f"/api/webapp/admin/arenas/{arena_id}",
            json={
                "schedule_mode": "season_closed",
                "reopen_date": "2026-12-01",
                "schedule_mode_note": "тест",
            },
        )
        assert ok.status_code == 200
    app.dependency_overrides.pop(get_admin_miniapp_principal, None)

    row = (
        await db_session.execute(
            text(
                "SELECT schedule_mode, reopen_date, schedule_mode_note FROM arena_profiles WHERE arena_id = :id"
            ),
            {"id": arena_id},
        )
    ).one()
    assert row[0] == "season_closed"
    assert str(row[1]) == "2026-12-01"
    assert row[2] == "тест"
