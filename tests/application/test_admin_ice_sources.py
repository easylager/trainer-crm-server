"""Admin «Источники расписаний»: mode derivation, health status, list query and save."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text

from src.application.admin_ice_sources import (
    SourceValidationError,
    detect_source_kind,
    effective_fetch_mode,
    health_status,
    list_admin_ice_sources,
    normalize_source_url,
    save_admin_ice_source,
)


def test_detect_source_kind():
    assert detect_source_kind("https://www.instagram.com/rink") == "instagram"
    assert detect_source_kind("https://vk.com/zor.zhlobin") == "vk"
    assert detect_source_kind("https://m.vk.com/x") == "vk"
    assert detect_source_kind("https://t.me/zorzhlobin") == "telegram"
    assert detect_source_kind("https://24afisha.by/ru/object/5159") == "afisha"
    assert detect_source_kind("https://rink.by/schedule") == "site"
    assert detect_source_kind(None) is None
    # a lookalike host must not count as Instagram
    assert detect_source_kind("https://notinstagram.com/x") == "site"


def test_normalize_source_url():
    assert normalize_source_url("  instagram.com/rink ") == "https://instagram.com/rink"
    assert normalize_source_url("") is None
    with pytest.raises(SourceValidationError):
        normalize_source_url("javascript:alert(1)")
    with pytest.raises(SourceValidationError):
        normalize_source_url("не ссылка")


def test_effective_mode_derivation():
    assert effective_fetch_mode("manual", None, False) == ("manual", True)
    assert effective_fetch_mode(None, None, False) == ("none", False)
    assert effective_fetch_mode(None, "manual_schedule_v1", False) == ("manual", False)
    assert effective_fetch_mode(None, "gorki_lds_v1", True) == ("byip", False)
    assert effective_fetch_mode(None, "zamok_html_v1", False) == ("server", False)
    # a switched-off job is nobody polling: entered by hand
    assert effective_fetch_mode(None, "weekly_grid_v1", False, job_enabled=False) == ("manual", False)


def test_health_status():
    assert health_status("none", 0, None, 0) == "none"
    assert health_status("manual", 14, "empty_after_slots", 18) == "ok"
    assert health_status("manual", 0, None, 0) == "waiting"
    assert health_status("server", 51, "timeout", 4) == "broken"
    assert health_status("server", 2, "empty_source", 0) == "empty"
    assert health_status("server", 0, None, 0) == "empty"
    assert health_status("server", 0, None, 5) == "ok"
    # empty-after-filter streaks are an empty source, not a broken one


@pytest.mark.asyncio
async def test_list_and_save_roundtrip(db_session):
    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9901, 'ТестГород', 'BY', true)"))
    await db_session.execute(
        text(
            "INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) "
            "VALUES (9902, 'Тест-арена', 9901, true, true, 'ice')"
        )
    )
    await db_session.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (9902, 9901, 'test-arena', 'published')")
    )
    await db_session.commit()

    data = await list_admin_ice_sources(db_session)
    item = next(i for i in data["items"] if i["arena_id"] == 9902)
    assert item["mode"] == "none" and item["status"] == "none" and item["source_url"] is None

    assert await save_admin_ice_source(
        db_session, arena_id=9902, source_url="instagram.com/test_rink", fetch_mode="manual",
        publish_days=[1, 0, 1], remind=True, admin_telegram_id=7,
    )
    data = await list_admin_ice_sources(db_session)
    item = next(i for i in data["items"] if i["arena_id"] == 9902)
    assert item["mode"] == "manual" and item["mode_set_by_admin"] is True
    assert item["source_kind"] == "instagram" and item["source_url"] == "https://instagram.com/test_rink"
    assert item["publish_days"] == [0, 1] and item["remind"] is True

    with pytest.raises(SourceValidationError):
        await save_admin_ice_source(
            db_session, arena_id=9902, source_url=None, fetch_mode="bogus", publish_days=[], remind=False,
            admin_telegram_id=7,
        )
    with pytest.raises(SourceValidationError):
        await save_admin_ice_source(
            db_session, arena_id=9902, source_url=None, fetch_mode="none", publish_days=[7], remind=False,
            admin_telegram_id=7,
        )
    assert not await save_admin_ice_source(
        db_session, arena_id=999999, source_url=None, fetch_mode="none", publish_days=[], remind=False,
        admin_telegram_id=7,
    )


@pytest.mark.asyncio
async def test_api_endpoints(db_session):
    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9911, 'ТестГород2', 'BY', true)"))
    await db_session.execute(
        text(
            "INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) "
            "VALUES (9912, 'Тест-арена 2', 9911, true, true, 'ice')"
        )
    )
    await db_session.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (9912, 9911, 'test-arena-2', 'published')")
    )
    await db_session.commit()
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/webapp/admin/ice-sources")
            assert r.status_code == 200 and any(i["arena_id"] == 9912 for i in r.json()["items"])
            ok = await c.put(
                "/api/webapp/admin/ice-sources/9912",
                json={"source_url": "vk.com/rink", "fetch_mode": "manual", "publish_days": [0], "remind": False},
            )
            assert ok.status_code == 200
            bad = await c.put("/api/webapp/admin/ice-sources/9912", json={"source_url": "x y", "fetch_mode": "manual"})
            assert bad.status_code == 400
            missing = await c.put("/api/webapp/admin/ice-sources/999999", json={"fetch_mode": "none"})
            assert missing.status_code == 404
            assert (await c.get("/webapp/admin-ice-sources")).status_code == 200
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)


def test_seed_plan_rules():
    from src.application.ice_sources_seed import plan_row

    def row(**kw):
        base = dict(arena_id=1, website_url="https://rink.by/", parser_key=None, config=None, has_row=False)
        base.update(kw)
        return SimpleNamespace(**base)

    # override wins, even over an existing admin row
    p = plan_row(row(has_row=True), {"source_url": "instagram.com/x", "fetch_mode": "manual"})
    assert p["origin"] == "override" and p["source_url"] == "https://instagram.com/x" and p["fetch_mode"] == "manual"
    # an existing row is never touched without an override
    assert plan_row(row(has_row=True), None) is None
    # no parser: «разобраться вручную», card link kept as a hint
    p = plan_row(row(), None)
    assert p["fetch_mode"] == "none" and p["source_url"] == "https://rink.by/" and p["origin"] == "card"
    # parser job → mode derived from it; bad card link becomes no link
    assert plan_row(row(parser_key="zamok_html_v1"), None)["fetch_mode"] == "server"
    assert plan_row(row(parser_key="manual_schedule_v1", website_url="не ссылка"), None)["source_url"] is None
    # no card link: fall back to the parser registry's link
    assert plan_row(row(website_url=None), None, "https://kobrininform.by/afisha/")["source_url"] == "https://kobrininform.by/afisha/"
    # a disabled parser job becomes manual
    assert plan_row(row(parser_key="weekly_grid_v1", job_enabled=False), None)["fetch_mode"] == "manual"


@pytest.mark.asyncio
async def test_seed_apply_respects_admin_edits(db_session):
    from src.application.ice_sources_seed import apply_seed, plan_seed

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9931, 'ТестГород4', 'BY', true)"))
    for aid, nm in ((9932, 'Арена A'), (9933, 'Арена B')):
        await db_session.execute(
            text("INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) VALUES (:i, :n, 9931, true, true, 'ice')"),
            {"i": aid, "n": nm},
        )
        await db_session.execute(
            text("INSERT INTO arena_profiles (arena_id, city_id, slug, status, website_url) VALUES (:i, 9931, :s, 'published', 'https://a.by/')"),
            {"i": aid, "s": f"arena-{aid}"},
        )
    await db_session.commit()
    await save_admin_ice_source(
        db_session, arena_id=9932, source_url="vk.com/mine", fetch_mode="manual", publish_days=[2], remind=True,
        admin_telegram_id=1,
    )
    plan = await plan_seed(db_session, {"9933": {"source_url": "t.me/b", "fetch_mode": "manual"}})
    ids = {p["arena_id"] for p in plan}
    assert 9932 not in ids and 9933 in ids  # the admin's row is left alone
    await apply_seed(db_session, plan)
    data = await list_admin_ice_sources(db_session)
    by = {i["arena_id"]: i for i in data["items"]}
    assert by[9932]["source_url"] == "https://vk.com/mine" and by[9932]["publish_days"] == [2]
    assert by[9933]["source_kind"] == "telegram" and by[9933]["mode"] == "manual"


# ── Журнал слотов и «N дней без слотов» ──────────────────────────────────


def test_staleness_rules():
    from datetime import date, datetime, timedelta, timezone

    from src.application.admin_ice_sources import log_bounds, staleness

    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    week = timedelta(days=7)
    # ровно через неделю без новых слотов — тревога; на минуту раньше — нет
    assert staleness("manual", now - week, None, now) == (True, 7)
    assert staleness("manual", now - week + timedelta(minutes=1), None, now) == (False, 6)
    # слотов не добавлялось ни разу: отсчёт от старта журнала
    assert staleness("server", None, now - timedelta(days=2), now) == (False, 2)
    assert staleness("server", None, now - timedelta(days=8), now) == (True, 8)
    # «разобраться вручную» не краснеет, нет журнала — нет вывода
    assert staleness("none", now - timedelta(days=30), None, now)[0] is False
    assert staleness("server", None, None, now) == (False, None)

    assert log_bounds(days=7, today=date(2026, 10, 27)) == (date(2026, 10, 21), date(2026, 10, 27))
    assert log_bounds(days=1, today=date(2026, 10, 27)) == (date(2026, 10, 27), date(2026, 10, 27))
    with pytest.raises(SourceValidationError):
        log_bounds(date_from=date(2026, 10, 5), date_to=date(2026, 10, 1))
    with pytest.raises(SourceValidationError):
        log_bounds(date_from=date(2026, 8, 1), date_to=date(2026, 10, 1))


async def _arena(db_session, city_id, arena_id, name):
    await db_session.execute(
        text("INSERT INTO arenas (id, name, city_id, is_active, is_confirmed, venue_type) VALUES (:i, :n, :c, true, true, 'ice')"),
        {"i": arena_id, "n": name, "c": city_id},
    )
    await db_session.execute(
        text("INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES (:i, :c, :s, 'published')"),
        {"i": arena_id, "c": city_id, "s": f"slug-{arena_id}"},
    )


async def _slot(db_session, arena_id, *, hours=48, source_id="run:1:x"):
    await db_session.execute(
        text(
            """
            INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local,
                ends_at_local, currency_code, status, source_id, schedule_basis)
            VALUES (:a, 'public_skate', now() + make_interval(hours => :h), now() + make_interval(hours => :h + 1),
                ((now() + make_interval(hours => :h)) AT TIME ZONE 'Europe/Minsk')::date,
                ((now() + make_interval(hours => :h)) AT TIME ZONE 'Europe/Minsk')::time,
                ((now() + make_interval(hours => :h + 1)) AT TIME ZONE 'Europe/Minsk')::time, 'BYN', 'active', :src, 'live')
            """
        ),
        {"a": arena_id, "h": hours, "src": source_id},
    )


@pytest.mark.asyncio
async def test_list_shows_stale_hidden_and_counts(db_session):
    from src.application.admin_ice_sources import HIDDEN_ARENA_IDS

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9941, 'ЖурналГород', 'BY', true)"))
    await _arena(db_session, 9941, 9942, "Свежая")
    await _arena(db_session, 9941, 9943, "Старая")
    await _arena(db_session, 9941, 9944, "Тихая новая")
    await _arena(db_session, 9941, HIDDEN_ARENA_IDS[0] + 90000, "Скрытая")
    await db_session.execute(text("UPDATE ice_session_journal_meta SET started_at = now() - interval '10 days'"))
    await _slot(db_session, 9942, hours=24)
    await _slot(db_session, 9942, hours=30)
    await _slot(db_session, 9943, hours=24)
    # у «Старой» последнее добавление 9 дней назад, у «Тихой новой» событий нет вовсе
    await db_session.execute(
        text("UPDATE ice_session_events SET occurred_at = now() - interval '9 days' WHERE arena_id = 9943")
    )
    await db_session.execute(
        text("INSERT INTO arena_schedule_sources (arena_id, fetch_mode) VALUES (9943, 'manual'), (9944, 'manual')")
    )
    await db_session.commit()

    data = await list_admin_ice_sources(db_session)
    by = {i["arena_id"]: i for i in data["items"]}
    assert by[9942]["added_7d"] == 2 and by[9942]["stale"] is False and by[9942]["days_since_added"] == 0
    assert by[9943]["stale"] is True and by[9943]["status"] == "stale" and by[9943]["days_since_added"] == 9
    assert by[9943]["added_7d"] == 0
    # событий нет: отсчёт от старта журнала (10 дней назад)
    assert by[9944]["stale"] is True and by[9944]["last_added_at"] is None
    assert data["counts"]["stale"] >= 2
    assert not any(i["arena_id"] in HIDDEN_ARENA_IDS for i in data["items"])
    order = [i["arena_id"] for i in data["items"] if i["arena_id"] in (9942, 9943, 9944)]
    assert order.index(9943) < order.index(9942)  # проблемные выше


@pytest.mark.asyncio
async def test_journal_groups_batches_and_filters(db_session):
    from src.application.admin_ice_sources import SourceValidationError, arena_log, journal

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9951, 'ЖурналГород2', 'BY', true)"))
    await _arena(db_session, 9951, 9952, "Каток А")
    await _arena(db_session, 9951, 9953, "Каток Б")
    await _slot(db_session, 9952, hours=24)
    await _slot(db_session, 9952, hours=30)
    await _slot(db_session, 9953, hours=24, source_id="admin")
    await db_session.execute(text("DELETE FROM ice_sessions WHERE arena_id = 9952 AND starts_at_utc > now() + interval '29 hours'"))
    await db_session.commit()

    data = await journal(db_session, days=7, city_id=9951)
    mine = [b for b in data["batches"] if b["arena_id"] in (9952, 9953)]
    a = next(b for b in mine if b["arena_id"] == 9952)
    # вставка и удаление в одной транзакции дают один пакет: +2 и −1
    assert len(a["added"]) == 2 and len(a["removed"]) == 1 and a["source"] == "parser"
    assert next(b for b in mine if b["arena_id"] == 9953)["source"] == "manual"
    assert data["totals"]["added"] == 3 and data["totals"]["removed"] == 1 and data["totals"]["arenas"] == 2
    assert {c["id"] for c in data["filters"]["cities"]} >= {9951}

    only_manual = await journal(db_session, days=7, city_id=9951, source="manual")
    assert {b["arena_id"] for b in only_manual["batches"]} == {9953}
    assert {q["arena_id"] for q in only_manual["quiet"]} == {9952}
    assert (await journal(db_session, days=7, arena_id=9952))["totals"]["arenas"] == 1
    with pytest.raises(SourceValidationError):
        await journal(db_session, source="bogus")

    log = await arena_log(db_session, 9953, days=7)
    assert log is not None and [b["source"] for b in log["batches"]] == ["manual"]
    assert await arena_log(db_session, 999999) is None


@pytest.mark.asyncio
async def test_log_api_endpoints(db_session):
    from httpx import ASGITransport, AsyncClient

    from src.api.app import app
    from src.api.miniapp_auth.deps import get_admin_miniapp_principal
    from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal

    await db_session.execute(text("INSERT INTO cities (id, name, country, is_active) VALUES (9961, 'ЖурналГород3', 'BY', true)"))
    await _arena(db_session, 9961, 9962, "Каток В")
    await _slot(db_session, 9962)
    await db_session.commit()
    app.dependency_overrides[get_admin_miniapp_principal] = lambda: MiniAppPrincipal(
        platform=MiniAppPlatform.TELEGRAM, user_id=4242
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/webapp/admin/ice-sources/9962/log?days=7")
            assert r.status_code == 200 and r.json()["batches"][0]["added"]
            assert (await c.get("/api/webapp/admin/ice-sources/999999/log")).status_code == 404
            r = await c.get("/api/webapp/admin/ice-log?days=7&arena_id=9962")
            assert r.status_code == 200 and r.json()["totals"]["added"] == 1
            assert (await c.get("/api/webapp/admin/ice-log?source=bogus")).status_code == 400
            assert (await c.get("/api/webapp/admin/ice-log?date_from=2026-10-05&date_to=2026-10-01")).status_code == 400
    finally:
        app.dependency_overrides.pop(get_admin_miniapp_principal, None)
