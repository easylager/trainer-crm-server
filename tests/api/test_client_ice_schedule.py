"""TASK-449: API расписания «Льда» v2 — флаг redesign_s4, форма ответа на сидированных данных."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.ice_schedule_v2 import invalidate_ice_schedule_cache
from src.application.ice_session_use_cases import create_ice_session
from sqlalchemy import text as _text
from src.shared.config import get_settings
from tests.api.test_public_arenas import _insert_arena, _insert_city
from tests.api.test_webapp_client_miniapp_integration import _client_auth_headers, patch_client_init_auth
from tests.conftest import unique_test_telegram_id

_MINSK = ZoneInfo("Europe/Minsk")


@pytest.fixture
def s4_env(monkeypatch: pytest.MonkeyPatch):
    def apply(ids: str | None) -> None:
        if ids is None:
            monkeypatch.delenv("CLIENT_REDESIGN_S4_TELEGRAM_IDS", raising=False)
        else:
            monkeypatch.setenv("CLIENT_REDESIGN_S4_TELEGRAM_IDS", ids)
        monkeypatch.delenv("CLIENT_REDESIGN_S4_PERCENT", raising=False)
        get_settings.cache_clear()
        invalidate_ice_schedule_cache()

    yield apply
    get_settings.cache_clear()
    invalidate_ice_schedule_cache()


async def _session(db_session, arena_id: int, when: datetime, kind: str, minutes: int = 60, **prices) -> int:
    local = when.astimezone(_MINSK)
    created = await create_ice_session(
        db_session,
        arena_id,
        local_date=local.date(),
        starts_at_local=local.strftime("%H:%M"),
        duration_minutes=minutes,
        kind=kind,
        **prices,
    )
    await db_session.flush()
    return int(created["id"])


@pytest.mark.asyncio
async def test_ice_schedule_flag_gate(app_use_test_db, db_session, s4_env) -> None:
    tid = unique_test_telegram_id()
    cid = await _insert_city(db_session, name=f"Расписание{uuid.uuid4().hex[:6]}")
    await db_session.commit()
    url = f"/api/webapp/client/ice/schedule?city_id={cid}&day=today&kind=skate"
    s4_env(None)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            off = await client.get(url, headers=_client_auth_headers())
            s4_env(str(tid))
            on = await client.get(url, headers=_client_auth_headers())
            bad = await client.get(url.replace("day=today", "day=nonsense"), headers=_client_auth_headers())
            bad_kind = await client.get(url.replace("kind=skate", "kind=nope"), headers=_client_auth_headers())
    assert off.status_code == 404
    assert on.status_code == 200, on.text
    assert on.headers["cache-control"] == "no-store"
    assert bad.status_code == 422 and bad_kind.status_code == 422


async def _real_city(db_session, name: str) -> int:
    """Реальный город — у выдуманных имён нет предложного падежа (city_locative — словарь)."""
    row = (await db_session.execute(_text("SELECT id FROM cities WHERE name = :n"), {"n": name})).first()
    if row:
        return int(row[0])
    return await _insert_city(db_session, name=name)


@pytest.mark.asyncio
async def test_ice_schedule_shape_and_filters(app_use_test_db, db_session, s4_env) -> None:
    tid = unique_test_telegram_id()
    cid = await _real_city(db_session, "Пинск")
    arena = await _insert_arena(db_session, cid, name="Каток А", has_photo=False)
    other = await _insert_arena(db_session, cid, name="Каток Б", has_photo=False)
    now = datetime.now(_MINSK)
    ongoing = await _session(db_session, arena, now - timedelta(minutes=30), "public_skate",
                             minutes=120, price_adult_minor=1200, price_rental_minor=800)
    soon = await _session(db_session, other, now + timedelta(hours=2), "family_skate")
    ohm = await _session(db_session, arena, now + timedelta(hours=4), "hockey_practice")
    tomorrow = now + timedelta(days=1)
    tm_id = await _session(db_session, arena, tomorrow.replace(hour=9, minute=0), "public_skate")
    await db_session.commit()

    s4_env(str(tid))
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get(f"/api/webapp/client/ice/schedule?city_id={cid}&day=today&kind=skate", headers=_client_auth_headers())
            r_ohm = await client.get(f"/api/webapp/client/ice/schedule?city_id={cid}&day=today&kind=ohm", headers=_client_auth_headers())
            r_week = await client.get(f"/api/webapp/client/ice/schedule?city_id={cid}&day=week&kind=skate", headers=_client_auth_headers())
    body = r.json()
    assert r.status_code == 200, r.text
    assert body["city"]["id"] == cid and body["city"]["name_in"] == "Пинске"
    ids_ongoing = [x["session_id"] for x in body["ongoing"]]
    assert ongoing in ids_ongoing and soon not in ids_ongoing
    assert [x["session_id"] for x in body["upcoming"]] == [soon]
    assert body["now_line"] and body["now_line"].startswith("Сейчас")
    got = body["ongoing"][0]
    assert got["minutes_left"] and got["minutes_left"] >= 60
    assert "до " in got["price_line"] and "12 BYN" in got["price_line"] and "прокат 8" in got["price_line"]
    assert got["href"].startswith("arena?ref=")
    kinds = {k["key"]: k for k in body["kinds"]}
    assert kinds["skate"]["count"] == 2 and kinds["ohm"]["count"] == 1
    assert body["tomorrow_morning"]["total"] == 1
    assert body["arenas"] and body["one_rink"] is False

    ohm_body = r_ohm.json()
    assert [x["session_id"] for x in ohm_body["upcoming"]] == [ohm]

    week = r_week.json()
    flat = [x["session_id"] for g in week["groups"] for x in g["rows"]]
    assert {ongoing, soon, tm_id} <= set(flat)
