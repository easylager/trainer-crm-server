"""TASK-446: интеграционные тесты «Я здесь» — /api/webapp/client/checkins* (флаг redesign_s5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.api.app import app
from src.shared.config import Settings, get_settings

from tests.api.test_webapp_client_miniapp_integration import (
    _cleanup_committed_seed,
    patch_client_init_auth,
)


def _tg() -> int:
    return 7_000_000_000 + (uuid.uuid4().int % 2_000_000_000)


def _enable_s5(monkeypatch, tg_id: int) -> None:
    monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", str(tg_id))
    monkeypatch.setenv("CLIENT_REDESIGN_S5_PERCENT", "0")
    get_settings.cache_clear()


async def _seed_checkin_env(*, name: str, tg_id: int, sessions: int = 1) -> tuple[int, int, list[int]]:
    """Город+каток+ИДУЩИЙ сеанс + клиент старше 7 дней — коммитом (route юзает get_session,
    но сидировать всё равно коммитом надёжнее: on_ice в bootstrap идёт через fan-out)."""
    engine = create_async_engine(Settings().database_url)
    session_ids: list[int] = []
    try:
        async with engine.begin() as conn:
            city_id = int((await conn.execute(
                text("INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                     "VALUES (:name, 'BY', 'BY_BASE', true, -1) RETURNING id"), {"name": name})).scalar_one())
            arena_id = int((await conn.execute(
                text("INSERT INTO arenas (city_id, name, address, venue_type, is_active, is_confirmed) "
                     "VALUES (:cid, :name, 'ул. Тестовая, 1', 'ice', true, true) RETURNING id"),
                {"cid": city_id, "name": f"Каток {name}"})).scalar_one())
            await conn.execute(
                text("INSERT INTO arena_profiles (arena_id, city_id, slug, status, amenities) "
                     "VALUES (:aid, :cid, :slug, 'published', CAST('{}' AS jsonb))"),
                {"aid": arena_id, "cid": city_id, "slug": f"ci-{arena_id}"})
            now = datetime.now(timezone.utc)
            for i in range(sessions):
                starts = now - timedelta(minutes=30 + 10 * i)
                ends = starts + timedelta(hours=2)
                local = (starts + timedelta(hours=3)).date()
                session_ids.append(int((await conn.execute(
                    text(
                        "INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,"
                        " starts_at_local, ends_at_local, currency_code, status, source_id, observed_at)"
                        " VALUES (:aid, 'public_skate', :s, :e, :d, :sl, :el, 'BYN', 'active', 'admin', :obs)"
                        " RETURNING id"),
                    {"aid": arena_id, "s": starts, "e": ends, "d": local,
                     "sl": (starts + timedelta(hours=3)).time(), "el": (ends + timedelta(hours=3)).time(),
                     "obs": now})).scalar_one()))
            await conn.execute(
                text("INSERT INTO clients (telegram_id, first_name, created_at) VALUES (:t, 'Максим', :c)"),
                {"t": tg_id, "c": now - timedelta(days=30)})
    finally:
        await engine.dispose()
    return city_id, arena_id, session_ids


async def _cleanup(*, city_id: int, arena_id: int, tg_id: int) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM ice_checkin_intents WHERE telegram_id = :t"), {"t": tg_id})
            await conn.execute(text("DELETE FROM ice_checkins WHERE telegram_id = :t"), {"t": tg_id})
            await conn.execute(text("DELETE FROM clients WHERE telegram_id = :t"), {"t": tg_id})
    finally:
        await engine.dispose()
    await _cleanup_committed_seed(city_id=city_id, arena_id=arena_id, tg_id=tg_id)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


H = {"X-Telegram-Init-Data": "mock"}


@pytest.mark.asyncio
async def test_checkins_flag_off_404(monkeypatch) -> None:
    """Без флага каждый эндпоинт 404 и home.on_ice нет."""
    tg = _tg()
    monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", "0")
    monkeypatch.setenv("CLIENT_REDESIGN_S5_PERCENT", "0")
    get_settings.cache_clear()
    try:
        with patch_client_init_auth(tg):
            async with await _client() as client:
                for resp in [
                    await client.post("/api/webapp/client/checkins", json={"session_id": 1}, headers=H),
                    await client.patch("/api/webapp/client/checkins/1", json={"load_level": 1}, headers=H),
                    await client.get("/api/webapp/client/checkins/state?session_ids=1", headers=H),
                    await client.post("/api/webapp/client/checkins/intent", json={"session_id": 1, "kind": "view"}, headers=H),
                    await client.post("/api/webapp/client/checkins/1/share", headers=H),
                ]:
                    assert resp.status_code == 404, (resp.request.url, resp.text)
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_checkin_happy_and_idempotent_and_patch(monkeypatch) -> None:
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ci-{uuid.uuid4().hex[:8]}", tg_id=tg)
    try:
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.post("/api/webapp/client/checkins",
                                      json={"session_id": sids[0], "load_level": 2}, headers=H)
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["checkin_id"] and body["session_id"] == sids[0]
                assert body["load_level"] == 2
                assert body["season_days"] == 1 and "раз за сезон" in body["nth_label"]
                assert body["live"]["level"] == 2 and body["live"]["count"] == 1
                # Дубликат — идемпотентен, тот же checkin_id
                r2 = await client.post("/api/webapp/client/checkins",
                                       json={"session_id": sids[0]}, headers=H)
                assert r2.status_code == 200 and r2.json()["checkin_id"] == body["checkin_id"]
                # PATCH после уже выставленной загрузки → 409
                rp = await client.patch(f"/api/webapp/client/checkins/{body['checkin_id']}",
                                        json={"load_level": 3}, headers=H)
                assert rp.status_code == 409, rp.text
                # state видит отметку
                rs = await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}", headers=H)
                st = rs.json()["sessions"][str(sids[0])]
                assert st["ongoing"] is True and st["checked_in"] is True
                assert st["checkin_id"] == body["checkin_id"] and st["load_level"] == 2
    finally:
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_checkin_not_ongoing_and_daily_limit(monkeypatch) -> None:
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ci-{uuid.uuid4().hex[:8]}", tg_id=tg, sessions=4)
    engine = create_async_engine(Settings().database_url)
    try:
        # будущий сеанс — not_ongoing
        async with engine.begin() as conn:
            now = datetime.now(timezone.utc)
            fut_s, fut_e = now + timedelta(hours=5), now + timedelta(hours=6)
            fut_id = int((await conn.execute(
                text("INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,"
                     " starts_at_local, ends_at_local, currency_code, status, source_id, observed_at)"
                     " VALUES (:a,'public_skate',:s,:e,:d,:sl,:el,'BYN','active','admin',:o) RETURNING id"),
                {"a": arena_id, "s": fut_s, "e": fut_e, "d": (fut_s + timedelta(hours=3)).date(),
                 "sl": (fut_s + timedelta(hours=3)).time(), "el": (fut_e + timedelta(hours=3)).time(),
                 "o": now})).scalar_one())
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.post("/api/webapp/client/checkins", json={"session_id": fut_id}, headers=H)
                assert r.status_code == 409 and r.json()["detail"]["code"] == "not_ongoing"
                r = await client.post("/api/webapp/client/checkins", json={"session_id": fut_id + 99999}, headers=H)
                assert r.status_code in (404, 409)
                # 3 сеанса — ок, 4-й → daily_limit
                for sid in sids[:3]:
                    rr = await client.post("/api/webapp/client/checkins", json={"session_id": sid}, headers=H)
                    assert rr.status_code == 200, rr.text
                rr = await client.post("/api/webapp/client/checkins", json={"session_id": sids[3]}, headers=H)
                assert rr.status_code == 409 and rr.json()["detail"]["code"] == "daily_limit"
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_checkin_intent_and_patch_and_share(monkeypatch) -> None:
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ci-{uuid.uuid4().hex[:8]}", tg_id=tg)
    try:
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.post("/api/webapp/client/checkins/intent",
                                      json={"session_id": sids[0], "kind": "route"}, headers=H)
                assert r.status_code == 204, r.text
                r = await client.post("/api/webapp/client/checkins", json={"session_id": sids[0]}, headers=H)
                cid = r.json()["checkin_id"]
                rp = await client.patch(f"/api/webapp/client/checkins/{cid}", json={"load_level": 1}, headers=H)
                assert rp.status_code == 200 and rp.json()["live"]["level"] == 1
                rs = await client.post(f"/api/webapp/client/checkins/{cid}/share", headers=H)
                assert rs.status_code == 200, rs.text
                sh = rs.json()
                assert "t.me/share/url" in sh["share_url"] and sh["text"]
        # intent записан
        engine = create_async_engine(Settings().database_url)
        async with engine.connect() as conn:
            n = (await conn.execute(
                text("SELECT COUNT(*) FROM ice_checkin_intents WHERE telegram_id = :t AND kind = 'route'"),
                {"t": tg})).scalar()
            assert n == 1
        await engine.dispose()
    finally:
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_helps_counted_once_and_rules(monkeypatch) -> None:
    """5.2: focus → ice_checkin_helps; своё не считается, дубликат — один раз."""
    reporter, viewer, own = _tg(), _tg(), _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"hp-{uuid.uuid4().hex[:8]}", tg_id=reporter)
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            for t in (viewer, own):
                await conn.execute(
                    text("INSERT INTO clients (telegram_id, first_name, created_at) VALUES (:t,'V',:c)"),
                    {"t": t, "c": datetime.now(timezone.utc) - timedelta(days=30)})
            # репортёр и «свой» аккаунт — свежие отметки с оценкой на одном сеансе
            for t in (reporter, own):
                await conn.execute(
                    text("INSERT INTO ice_checkins (telegram_id, session_id, arena_id, local_date, load_level, source, counts_for_load, load_set_at)"
                         " VALUES (:t,:s,:a,:d,2,'app',true,:n)"),
                    {"t": t, "s": sids[0], "a": arena_id,
                     "d": datetime.now(timezone.utc).astimezone().date(), "n": datetime.now(timezone.utc)})
        _enable_s5(monkeypatch, viewer)
        with patch_client_init_auth(viewer):
            async with await _client() as client:
                r = await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}&focus={sids[0]}", headers=H)
                assert r.status_code == 200, r.text
                await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}&focus={sids[0]}", headers=H)
        _enable_s5(monkeypatch, own)
        with patch_client_init_auth(own):
            async with await _client() as client:
                await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}&focus={sids[0]}", headers=H)
        async with engine.connect() as conn:
            helps = (await conn.execute(
                text("SELECT reporter_telegram_id, viewer_telegram_id FROM ice_checkin_helps"))).mappings().all()
            to_viewer = [h for h in helps if int(h["viewer_telegram_id"]) == viewer]
            # viewer засчитал обоих чужих репортёров, по разу несмотря на повторный focus
            assert {int(h["reporter_telegram_id"]) for h in to_viewer} == {reporter, own}
            to_own = [h for h in helps if int(h["viewer_telegram_id"]) == own]
            # свой аккаунт сам себе не засчитывается → только reporter
            assert {int(h["reporter_telegram_id"]) for h in to_own} == {reporter}
        _enable_s5(monkeypatch, reporter)
        with patch_client_init_auth(reporter):
            async with await _client() as client:
                r = await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}", headers=H)
                assert r.json()["me"]["helped"] == 2
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        eng = create_async_engine(Settings().database_url)
        async with eng.begin() as conn:
            await conn.execute(text("DELETE FROM ice_checkin_helps WHERE viewer_telegram_id = ANY(:v)"), {"v": [viewer, own]})
            await conn.execute(text("DELETE FROM ice_checkins WHERE telegram_id = ANY(:v)"), {"v": [viewer, own, reporter]})
            await conn.execute(text("DELETE FROM clients WHERE telegram_id = ANY(:v)"), {"v": [viewer, own]})
        await eng.dispose()
        await _cleanup_committed_seed(city_id=city_id, arena_id=arena_id, tg_id=reporter)


@pytest.mark.asyncio
async def test_helps_stale_report_not_credited(monkeypatch) -> None:
    """Оценка старше 40 минут при открытии сеанса — «помог» не засчитывается."""
    reporter, viewer = _tg(), _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"hp-{uuid.uuid4().hex[:8]}", tg_id=reporter)
    engine = create_async_engine(Settings().database_url)
    try:
        old = datetime.now(timezone.utc) - timedelta(minutes=50)
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO clients (telegram_id, first_name, created_at) VALUES (:t,'V',:c)"),
                {"t": viewer, "c": old})
            await conn.execute(
                text("INSERT INTO ice_checkins (telegram_id, session_id, arena_id, local_date, load_level, source, counts_for_load, created_at, load_set_at)"
                     " VALUES (:t,:s,:a,:d,3,'app',true,:o,:o)"),
                {"t": reporter, "s": sids[0], "a": arena_id,
                 "d": old.astimezone().date(), "o": old})
        _enable_s5(monkeypatch, viewer)
        with patch_client_init_auth(viewer):
            async with await _client() as client:
                await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}&focus={sids[0]}", headers=H)
        async with engine.connect() as conn:
            n = (await conn.execute(
                text("SELECT COUNT(*) FROM ice_checkin_helps WHERE viewer_telegram_id=:v"), {"v": viewer})).scalar()
            assert n == 0
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        eng = create_async_engine(Settings().database_url)
        async with eng.begin() as conn:
            await conn.execute(text("DELETE FROM ice_checkin_helps WHERE viewer_telegram_id=:v"), {"v": viewer})
            await conn.execute(text("DELETE FROM ice_checkins WHERE telegram_id=:t"), {"t": reporter})
            await conn.execute(text("DELETE FROM clients WHERE telegram_id=:t"), {"t": viewer})
        await eng.dispose()
        await _cleanup_committed_seed(city_id=city_id, arena_id=arena_id, tg_id=reporter)


@pytest.mark.asyncio
async def test_bootstrap_on_ice(monkeypatch) -> None:
    """s5 + идущий сеанс + intent сегодня → home.on_ice в bootstrap."""
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ci-{uuid.uuid4().hex[:8]}", tg_id=tg)
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO ice_checkin_intents (telegram_id, session_id, kind) VALUES (:t, :s, 'view')"),
                {"t": tg, "s": sids[0]})
            await conn.execute(
                text("INSERT INTO client_sessions (telegram_id, state, city_id) VALUES (:t, 'city_selected', :c) "
                     "ON CONFLICT (telegram_id) DO UPDATE SET city_id = :c"),
                {"t": tg, "c": city_id})
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                resp = await client.get("/api/webapp/client/hub/bootstrap", headers=H)
        assert resp.status_code == 200, resp.text
        oi = (resp.json().get("home") or {}).get("on_ice")
        assert oi is not None, resp.text[:2000]
        assert oi["session_id"] == sids[0] and oi["arena_id"] == arena_id
        assert oi["checked_in"] is False and oi["arena_name"]
        assert isinstance(oi["minutes_left"], int) and oi["minutes_left"] > 0
        assert "invite_url" in oi and oi["invite_url"]
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)
