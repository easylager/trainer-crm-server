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


@pytest.fixture
def s5_env(monkeypatch: pytest.MonkeyPatch):
    def apply(ids: str | None) -> None:
        if ids is None:
            monkeypatch.delenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", raising=False)
        else:
            monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", ids)
        monkeypatch.delenv("CLIENT_REDESIGN_S5_PERCENT", raising=False)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


async def _company_for(db_session, session_id: int, telegram_id: int) -> str:
    """Открытая компания на сеанс + ответ организатора (минимум для my_open_companies)."""
    from src.application.ice_company.codes import new_public_code, tg_participant_key

    ev = (
        await db_session.execute(
            _text(
                """
                SELECT s.id, s.kind, s.starts_at_utc, s.ends_at_utc, s.arena_id,
                       a.name AS arena_name, a.city_id
                FROM ice_sessions s JOIN arenas a ON a.id = s.arena_id WHERE s.id = :id
                """
            ),
            {"id": session_id},
        )
    ).mappings().one()
    event_id = (
        await db_session.execute(
            _text(
                """
                INSERT INTO ice_company_events (kind, source_ref, starts_at, ends_at, venue_ref, venue_label, city_id, cancelled)
                VALUES (:k, :src, :st, :en, :vref, :vlabel, :cid, false) RETURNING id
                """
            ),
            {
                "k": str(ev["kind"]), "src": f"ice_session:{session_id}",
                "st": ev["starts_at_utc"], "en": ev["ends_at_utc"],
                "vref": f"arena:{int(ev['arena_id'])}", "vlabel": str(ev["arena_name"]),
                "cid": int(ev["city_id"]),
            },
        )
    ).scalar_one()
    code = new_public_code()
    cid2 = (
        await db_session.execute(
            _text(
                """
                INSERT INTO ice_companies (public_code, name, organizer_ref, event_id, event_version, status, expires_at)
                VALUES (:code, 'Каток', :org, :eid, 1, 'open', :exp) RETURNING id
                """
            ),
            {"code": code, "org": tg_participant_key(telegram_id), "eid": event_id, "exp": ev["ends_at_utc"] + timedelta(days=30)},
        )
    ).scalar_one()
    await db_session.execute(
        _text(
            """
            INSERT INTO ice_company_responses (company_id, participant_key, display_name, status, source)
            VALUES (:c, :k, 'Я', 'going', 'tg')
            """
        ),
        {"c": cid2, "k": tg_participant_key(telegram_id)},
    )
    return code


@pytest.mark.asyncio
async def test_ice_schedule_company_under_s5(app_use_test_db, db_session, s4_env, s5_env, monkeypatch) -> None:
    """Без s5 поля company нет; с s5 — на сеансе моей компании плашка {code,going_count,page_url}."""
    tid = unique_test_telegram_id()
    cid = await _real_city(db_session, "Пинск")
    arena = await _insert_arena(db_session, cid, name="Каток А", has_photo=False)
    now = datetime.now(_MINSK)
    sid = await _session(db_session, arena, now + timedelta(hours=2), "public_skate")
    code = await _company_for(db_session, sid, tid)
    await db_session.commit()

    url = f"/api/webapp/client/ice/schedule?city_id={cid}&day=today&kind=skate"
    s4_env(str(tid))
    s5_env(None)
    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            off = await client.get(url, headers=_client_auth_headers())
            assert off.status_code == 200, off.text
            rows = off.json().get("upcoming") or []
            assert all("company" not in r for r in rows)
            assert "company_share" not in off.json()

            s5_env(str(tid))
            on = await client.get(url, headers=_client_auth_headers())
            body = on.json()
            rows = [r for r in (body.get("upcoming") or []) if r.get("session_id") == sid]
            assert rows and rows[0]["company"]["code"] == code
            assert rows[0]["company"]["going_count"] == 1
            assert rows[0]["company"]["page_url"].endswith(f"/k/{code}")
    s5_env(None)
