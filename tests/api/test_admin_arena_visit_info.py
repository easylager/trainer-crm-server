"""Карточка катка v2: visit_info через админку и публичную карточку Mini App."""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from tests.api.test_admin_arena_profile import patch_admin_principal
from tests.api.test_public_arenas import _insert_arena, _insert_city

_VISIT = {
    "tickets": {"mode": "box_office", "open": "9:00", "close": "21:00", "card": True, "cash": False, "junk": 1},
    "child_age_max": 12,
    "facts": {"cafe": {"state": "yes", "note": "кофе"}, "warmth": {"state": "cold"}},
    "custom_facts": [{"icon": "info", "title": "Есть лавочки", "note": ""}],
    "services": [{"kind": "rental", "label": "", "price": "8 BYN", "note": ""}],
}


@pytest.mark.asyncio
async def test_admin_visit_info_roundtrip_and_public_visit(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"Visit-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Каток с карточкой")
    await db_session.commit()

    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(f"/api/webapp/admin/arenas/{arena_id}", json={"visit_info": _VISIT})
            assert resp.status_code == 200, resp.text
            got = await client.get("/api/webapp/admin/arenas", params={"city_id": cid})
            card = await client.get(f"/api/public/arenas/{arena_id}")

    row = next(a for a in got.json()["items"] if a["id"] == arena_id)
    stored = row["visit_info"]
    assert stored["tickets"] == {
        "mode": "box_office", "open": "09:00", "close": "21:00", "card": True, "cash": False,
    }
    assert stored["child_age_max"] == 12
    assert stored["facts"]["cafe"] == {"state": "yes", "note": "кофе"}

    assert card.status_code == 200, card.text
    body = card.json()
    assert body["visit_info"] == stored
    visit = body["visit"]
    assert visit["blocks"][0] == "cover"
    assert visit["tickets"]["mode"] == "box_office"
    titles = [f["title"] for f in visit["facts"]]
    assert "Кафе" in titles and "Внутри холодно" in titles and "Есть лавочки" in titles
    assert any(r["kind"] == "rental" and r["price"] == "8 BYN" for r in visit["services"]["rows"])


@pytest.mark.asyncio
async def test_admin_visit_info_invalid_is_422_and_not_stored(app_use_test_db, db_session) -> None:
    cid = await _insert_city(db_session, name=f"VisitBad-{uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, cid, name="Каток без карточки")
    await db_session.commit()

    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            bad = await client.patch(
                f"/api/webapp/admin/arenas/{arena_id}",
                json={"visit_info": {"tickets": {"mode": "teleport"}}},
            )
            got = await client.get("/api/webapp/admin/arenas", params={"city_id": cid})
            card = await client.get(f"/api/public/arenas/{arena_id}")

    assert bad.status_code == 422
    assert "tickets.mode" in bad.json()["detail"]
    row = next(a for a in got.json()["items"] if a["id"] == arena_id)
    assert row["visit_info"] == {}
    assert card.json()["visit"]["facts"] == []
