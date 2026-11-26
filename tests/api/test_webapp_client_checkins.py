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
                    # TASK-451: значки — те же 404 без флага
                    await client.post("/api/webapp/client/badges/seen", json={"keys": ["first_ice"]}, headers=H),
                    await client.get("/api/webapp/client/badges/first_ice/share", headers=H),
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
                # PATCH пока сеанс идёт — переписывает оценку (фикс-пак ревью)
                rp = await client.patch(f"/api/webapp/client/checkins/{body['checkin_id']}",
                                        json={"load_level": 3}, headers=H)
                assert rp.status_code == 200, rp.text
                # state видит отметку с новой оценкой
                rs = await client.get(f"/api/webapp/client/checkins/state?session_ids={sids[0]}", headers=H)
                st = rs.json()["sessions"][str(sids[0])]
                assert st["ongoing"] is True and st["checked_in"] is True
                assert st["checkin_id"] == body["checkin_id"] and st["load_level"] == 3
    finally:
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_checkin_load_already_set_after_end(monkeypatch) -> None:
    """Фикс-пак ревью: пока сеанс идёт — оценку можно переписать; после конца — 409 already_set."""
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ci-{uuid.uuid4().hex[:8]}", tg_id=tg)
    engine = create_async_engine(Settings().database_url)
    try:
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.post("/api/webapp/client/checkins",
                                      json={"session_id": sids[0], "load_level": 1}, headers=H)
                assert r.status_code == 200, r.text
                cid = r.json()["checkin_id"]
        # Сеанс только что закончился (внутри 40-мин запаса) — повтор всё равно уже нельзя.
        # Сдвигаем обе границы: ck_ice_sessions_duration требует минимальную длину.
        async with engine.begin() as conn:
            now = datetime.now(timezone.utc)
            await conn.execute(
                text("UPDATE ice_sessions SET starts_at_utc = :s, ends_at_utc = :e WHERE id = :id"),
                {"s": now - timedelta(minutes=100), "e": now - timedelta(minutes=10), "id": sids[0]})
        with patch_client_init_auth(tg):
            async with await _client() as client:
                rp = await client.patch(f"/api/webapp/client/checkins/{cid}",
                                        json={"load_level": 2}, headers=H)
                assert rp.status_code == 409 and rp.json()["detail"]["code"] == "already_set", rp.text
    finally:
        await engine.dispose()
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
        assert oi["next_badge"] and oi["next_badge"]["name"] == "Не растаял"
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_checkin_badges_award_seen_share_and_me(monkeypatch) -> None:
    """TASK-451: check-in вручает «Вышел на лёд»; pending в bootstrap; seen; share; badges в /client/me."""
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"bd-{uuid.uuid4().hex[:8]}", tg_id=tg)
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO client_sessions (telegram_id, state, city_id) VALUES (:t, 'city_selected', :c) "
                     "ON CONFLICT (telegram_id) DO UPDATE SET city_id = :c"),
                {"t": tg, "c": city_id})
        _enable_s5(monkeypatch, tg)
        monkeypatch.setenv("CLIENT_REDESIGN_S4_TELEGRAM_IDS", str(tg))
        monkeypatch.setenv("CLIENT_REDESIGN_S4_PERCENT", "0")
        get_settings.cache_clear()
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.post("/api/webapp/client/checkins",
                                      json={"session_id": sids[0]}, headers=H)
                assert r.status_code == 200, r.text
                earned = r.json()["earned_badges"]
                assert [b["key"] for b in earned] == ["first_ice"]
                assert earned[0]["earned"] is True and earned[0]["progress"]["total"] == 1
                # bootstrap: лист вручения ждёт показа
                rb = await client.get("/api/webapp/client/hub/bootstrap", headers=H)
                pend = (rb.json().get("home") or {}).get("pending_badges")
                assert pend and pend[0]["key"] == "first_ice" and pend[0]["earned"] is True
                # /client/me под s4+s5: все 6 значков
                rm = await client.get("/api/webapp/client/me", headers=H)
                badges = rm.json().get("badges")
                assert badges and len(badges) == 6
                by_key = {b["key"]: b for b in badges}
                assert by_key["first_ice"]["earned"] is True
                assert by_key["first_ice"]["earned_at"]
                assert by_key["streak_3"]["earned"] is False
                assert by_key["streak_3"]["progress"] == {"done": 1, "total": 3}
                # share endpoint
                rh = await client.get("/api/webapp/client/badges/first_ice/share", headers=H)
                assert rh.status_code == 200, rh.text
                sj = rh.json()
                assert sj["share_url"] and "badge_first_ice" in sj["share_url"]
                assert "Вышел на лёд" in sj["share_text"] and "Максим" in sj["share_text"]
                assert (await client.get("/api/webapp/client/badges/nope/share", headers=H)).status_code == 404
                # seen → pending пуст
                rs = await client.post("/api/webapp/client/badges/seen",
                                       json={"keys": ["first_ice", "bogus"]}, headers=H)
                assert rs.status_code == 200 and rs.json()["shown"] == 1
                rb2 = await client.get("/api/webapp/client/hub/bootstrap", headers=H)
                assert not (rb2.json().get("home") or {}).get("pending_badges")
                # повторный seen — 0 (shown_at уже стоит)
                rs2 = await client.post("/api/webapp/client/badges/seen",
                                        json={"keys": ["first_ice"]}, headers=H)
                assert rs2.json()["shown"] == 0
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        eng = create_async_engine(Settings().database_url)
        async with eng.begin() as conn:
            await conn.execute(text("DELETE FROM ice_badges WHERE telegram_id = :t"), {"t": tg})
            await conn.execute(text("DELETE FROM client_sessions WHERE telegram_id = :t"), {"t": tg})
        await eng.dispose()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


# ── TASK-452 (5.5): «обычно» — blended-оценка и сетка «Когда свободнее» ────────


def _invalidate_usual_caches() -> None:
    from src.application import ice_usual_load as iul
    from src.application import session_load as sl
    from src.application.ice_schedule_v2 import invalidate_ice_schedule_cache

    iul.invalidate_usual_cache()
    sl.invalidate_session_load_cache()
    invalidate_ice_schedule_cache()


async def _seed_calm_reports(arena_id: int, session_id: int, *, n: int = 6) -> tuple[int, int]:
    """n чужих «свободно» на сеансе → ячейка (weekday, bucket) сеанса. Возвращает (wd, bucket)."""
    from src.application import ice_usual_load as iul

    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            sess = (
                await conn.execute(
                    text("SELECT local_date, starts_at_local FROM ice_sessions WHERE id = :s"),
                    {"s": session_id},
                )
            ).mappings().one()
            now = datetime.now(timezone.utc)
            for _ in range(n):
                await conn.execute(
                    text("INSERT INTO ice_checkins (telegram_id, session_id, arena_id, local_date,"
                         " load_level, source, counts_for_load, load_set_at)"
                         " VALUES (:t,:s,:a,:d,1,'app',true,:n)"),
                    {"t": _tg(), "s": session_id, "a": arena_id, "d": sess["local_date"], "n": now})
        wd = sess["local_date"].weekday()
        return wd, iul.bucket_for_hour(sess["starts_at_local"].hour)
    finally:
        await engine.dispose()


async def _cleanup_reports(arena_id: int) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM ice_checkins WHERE arena_id = :a"), {"a": arena_id})
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_state_usual_blended_and_arena_grid(monkeypatch) -> None:
    """state: usual на сеансе (blend 6×«свободно» → calm при любом prior) + arena_usual."""
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ul-{uuid.uuid4().hex[:8]}", tg_id=tg)
    try:
        wd, bucket = await _seed_calm_reports(arena_id, sids[0])
        _invalidate_usual_caches()
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                rs = await client.get(
                    f"/api/webapp/client/checkins/state?session_ids={sids[0]}&arena_id={arena_id}",
                    headers=H,
                )
                assert rs.status_code == 200, rs.text
                body = rs.json()
                st = body["sessions"][str(sids[0])]
                # (prior·4 + 6·1 + 0.5·6)/(4+6+3) ≤ 1.62 < 1.67 → «свободно» при любом prior
                assert st["usual"] == {"key": "calm", "word": "свободно"}, st
                g = body["arena_usual"]
                assert g is not None, body
                assert g["total"] == 6
                assert g["buckets"] == [10, 14, 18, 20]
                assert len(g["cells"]) == 4 and all(len(row) == 7 for row in g["cells"])
                assert g["cells"][bucket][wd] == 1
                # дефолтные правила миграции дают prior всем ячейкам — «мало данных» нет
                assert all(v is not None for row in g["cells"] for v in row)
                # без arena_id сетка не грузится
                rs2 = await client.get(
                    f"/api/webapp/client/checkins/state?session_ids={sids[0]}", headers=H)
                assert rs2.json()["arena_usual"] is None
    finally:
        _invalidate_usual_caches()
        get_settings.cache_clear()
        await _cleanup_reports(arena_id)
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)


@pytest.mark.asyncio
async def test_ice_schedule_usual_rows_flag(monkeypatch) -> None:
    """schedule: usual на строках под s5; без s5 ключа нет, admin-оценка как раньше."""
    tg = _tg()
    city_id, arena_id, sids = await _seed_checkin_env(name=f"ul-{uuid.uuid4().hex[:8]}", tg_id=tg)
    try:
        _invalidate_usual_caches()
        monkeypatch.setenv("CLIENT_REDESIGN_S4_TELEGRAM_IDS", str(tg))
        monkeypatch.setenv("CLIENT_REDESIGN_S4_PERCENT", "0")
        _enable_s5(monkeypatch, tg)
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.get(
                    f"/api/webapp/client/ice/schedule?city_id={city_id}&day=today&kind=skate",
                    headers=H,
                )
                assert r.status_code == 200, r.text
                payload = r.json()
                rows = (
                    list(payload.get("ongoing") or [])
                    + list(payload.get("upcoming") or [])
                    + [x for g in payload.get("groups") or [] for x in g.get("rows") or []]
                )
                mine = [x for x in rows if x.get("session_id") == sids[0]]
                assert mine, f"сеанс {sids[0]} не найден в payload: {list(payload.keys())}"
                u = mine[0].get("usual")
                assert u and u["key"] in ("calm", "medium", "busy") and u["word"], mine[0]
        # флаг выключен: строка есть, usual нет
        monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", "0")
        get_settings.cache_clear()
        with patch_client_init_auth(tg):
            async with await _client() as client:
                r = await client.get(
                    f"/api/webapp/client/ice/schedule?city_id={city_id}&day=today&kind=skate",
                    headers=H,
                )
                assert r.status_code == 200, r.text
                payload = r.json()
                rows = (
                    list(payload.get("ongoing") or [])
                    + list(payload.get("upcoming") or [])
                    + [x for g in payload.get("groups") or [] for x in g.get("rows") or []]
                )
                mine = [x for x in rows if x.get("session_id") == sids[0]]
                assert mine and "usual" not in mine[0]
    finally:
        _invalidate_usual_caches()
        get_settings.cache_clear()
        await _cleanup(city_id=city_id, arena_id=arena_id, tg_id=tg)
