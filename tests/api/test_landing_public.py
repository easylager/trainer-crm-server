"""Public Glide landing API and SSR entry."""
from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.routes.public import reset_trainer_start_limiter_for_tests
from src.application.landing_manifest import clear_landing_manifest_cache_for_tests
from src.application.landing_trainer_start_use_cases import (
    build_trainer_bot_deep_link,
    build_trainer_bot_join_deep_link,
    sanitize_referral_code,
)
from src.shared.config import Settings


def _landing_settings(**overrides):
    base = Settings()
    data = base.model_dump()
    data.update(overrides)
    return Settings.model_validate(data)


@pytest.fixture(autouse=True)
def _reset_landing_limiter():
    reset_trainer_start_limiter_for_tests()
    clear_landing_manifest_cache_for_tests()
    yield
    reset_trainer_start_limiter_for_tests()
    clear_landing_manifest_cache_for_tests()


def test_sanitize_referral_code():
    assert sanitize_referral_code("ABC12") == "ABC12"
    assert sanitize_referral_code("  x9  ") == "x9"
    assert sanitize_referral_code("bad-code!") is None
    assert sanitize_referral_code("") is None
    assert sanitize_referral_code(None) is None


def test_build_trainer_bot_deep_link_with_referral():
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    url = build_trainer_bot_deep_link("tok123", referral_code="REF1", settings=s)
    assert url == "https://t.me/IceProTestBot?start=link_tok123_ref_REF1"


def test_build_trainer_bot_join_deep_link():
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    assert build_trainer_bot_join_deep_link(settings=s) == "https://t.me/IceProTestBot?start=join"
    assert build_trainer_bot_join_deep_link(settings=_landing_settings(trainer_bot_username=None)) is None


@pytest.mark.asyncio
async def test_landing_config_public(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/public/landing-config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["vertical"] == "ice"
    assert data["market"] == "by"
    assert data["brand"]["name"] == "Glide"
    assert data["registration_enabled"] is True
    assert "hero" in data and "bento" in data
    assert "value_pillars" in data and len(data["value_pillars"]) == 4
    assert "activation_arc" in data and len(data["activation_arc"]) == 4
    assert data.get("sections", {}).get("bento_heading")
    assert data.get("sections", {}).get("arc_heading")
    assert data.get("sections", {}).get("steps_heading")
    assert data.get("join_url") == "/join"
    assert data.get("telegram_join_url") == "https://t.me/IceProTestBot?start=join"


@pytest.mark.asyncio
async def test_landing_trainers_injects_config_script(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/trainers")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert 'data-vertical="ice"' in body
    assert 'id="landing-config"' in body
    assert "Glide" in body
    assert 'id="hero"' in body
    assert "landing-live-link.css" in body
    assert 'rel="canonical"' in body
    assert "/trainers" in body


@pytest.mark.asyncio
async def test_landing_trainers_is_part_of_the_site(monkeypatch):
    """Лендинг тренера — страница glideclub.by: путь на главную, общий подвал и шрифты, JSON-LD."""
    s = _landing_settings(trainer_bot_username="IceProTestBot", webapp_base_url="https://glideclub.by")
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/trainers")
        raw = await client.get("/landing/index.html", follow_redirects=False)
    body = resp.text
    assert "__" + "SITE_FOOTER__" not in body and "__LANDING_SITE_HEAD__" not in body
    assert '<a class="logo" id="logoBox" href="/"' in body
    assert 'class="b-site-foot"' in body
    assert '<a href="/">Расписание катков по Беларуси</a>' in body
    assert "b-site-foot__tg" not in body  # кнопка клиентского бота тренеру не нужна
    # Кнопки — ссылки, а не <button>: поисковик видит путь регистрации.
    assert body.count('class="cta cta--') == 3
    assert body.count('href="/join">Начать в Telegram</a>') == 3
    assert "fonts.googleapis.com" not in body
    assert "/static/shared/glide-public-fonts.css" in body
    assert 'lang="ru-BY">' in body.split("<head>", 1)[0]
    assert body.count("<h1") == 1
    assert "Всё рабочее пространство тренера — в одном месте</h2>" in body
    assert body.count("в одном месте</h2>") == 1
    ld_raw = body.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
    graph = json.loads(ld_raw)["@graph"]
    crumbs = next(n for n in graph if n["@type"] == "BreadcrumbList")["itemListElement"]
    assert [c["item"] for c in crumbs] == ["https://glideclub.by/", "https://glideclub.by/trainers"]
    assert raw.status_code == 301 and raw.headers["location"] == "/trainers"


@pytest.mark.asyncio
async def test_trainer_start_happy_path(db_session, monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_start_max_requests=20)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)

    before = await db_session.execute(text("SELECT COUNT(*) FROM trainers"))
    trainers_before = int(before.scalar() or 0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/public/trainer-start",
            json={"referral_code": "REF9"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["trainer_id"] is None
    assert data["redirect_url"].startswith("https://t.me/IceProTestBot?start=link_")
    assert "_ref_REF9" in data["redirect_url"]
    assert data.get("expires_at")

    after = await db_session.execute(text("SELECT COUNT(*) FROM trainers"))
    assert int(after.scalar() or 0) == trainers_before

    token = data["redirect_url"].split("start=link_", 1)[1].split("_ref_", 1)[0]
    row = await db_session.execute(
        text("SELECT trainer_id, used_at FROM trainer_link_tokens WHERE token = :tok"),
        {"tok": token},
    )
    tok_row = row.fetchone()
    assert tok_row is not None
    assert tok_row[0] is None
    assert tok_row[1] is None


@pytest.mark.asyncio
async def test_trainer_join_get_redirect(db_session, monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_start_max_requests=20)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        resp = await client.get("/join?ref=REF9")
    assert resp.status_code == 302
    location = resp.headers.get("location") or ""
    assert location.startswith("https://t.me/IceProTestBot?start=link_")
    assert "_ref_REF9" in location


@pytest.mark.asyncio
async def test_landing_trainers_preview_cover_and_analytics(monkeypatch):
    """Превью в мессенджерах — обложка 1200×630; Метрика и GA — как на остальном сайте; HEAD отвечает."""
    s = _landing_settings(
        trainer_bot_username="IceProTestBot",
        webapp_base_url="https://glideclub.by",
        yandex_metrika_counter_id=12345,
        google_analytics_measurement_id="G-ABC1234",
    )
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/trainers")
        head = await client.head("/trainers")
        cover = await client.get("/landing/og-trainers.png")
    body = resp.text
    assert '<meta property="og:image" content="https://glideclub.by/landing/og-trainers.png">' in body
    assert '<meta name="twitter:image" content="https://glideclub.by/landing/og-trainers.png">' in body
    assert '<meta property="og:image:width" content="1200">' in body
    assert '<meta property="og:image:height" content="630">' in body
    assert "<title>CRM для тренера по фигурному катанию и хоккею — Glide</title>" in body
    assert "__PUBLIC_ANALYTICS_HEAD__" not in body
    assert "mc.yandex.ru/metrika/tag.js?id=12345" in body
    assert "googletagmanager.com/gtag/js?id=G-ABC1234" in body
    assert '"ym_counter_id": 12345' in body
    assert head.status_code == 200
    assert cover.status_code == 200 and cover.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_landing_trainers_without_counters_has_no_analytics(monkeypatch):
    s = _landing_settings(
        trainer_bot_username="IceProTestBot",
        yandex_metrika_counter_id=None,
        google_analytics_measurement_id=None,
    )
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/trainers")).text
    assert "__PUBLIC_ANALYTICS_HEAD__" not in body
    assert "mc.yandex" not in body and "googletagmanager" not in body
    assert "ym_counter_id" not in body


@pytest.mark.asyncio
async def test_trainer_join_records_source_in_audit(db_session, monkeypatch):
    """UTM и внешний сайт-источник с лендинга попадают в аудит /join — иначе канал тренеров не виден."""
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_start_max_requests=20)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "src.api.routes.public.audit_log",
        lambda event, actor_type, actor_id, payload=None: events.append((event, payload or {})),
    )
    long_campaign = "x" * 200
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        resp = await client.get(
            f"/join?utm_source=instagram&utm_medium=bio&utm_campaign={long_campaign}&from=l.instagram.com&junk=1"
        )
    assert resp.status_code == 302
    payload = next(p for e, p in events if e == "landing.trainer_join_redirect")
    assert payload["utm_source"] == "instagram"
    assert payload["utm_medium"] == "bio"
    assert payload["utm_campaign"] == "x" * 64
    assert payload["from"] == "l.instagram.com"
    assert "junk" not in payload


@pytest.mark.asyncio
async def test_trainer_join_get_disabled(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_registration_enabled=False)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/join")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_trainer_start_disabled(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_registration_enabled=False)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/public/trainer-start", json={})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_trainer_start_missing_bot_username(monkeypatch):
    s = _landing_settings(trainer_bot_username=None)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/public/trainer-start", json={})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_trainer_start_honeypot_rejected(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/public/trainer-start",
            json={"website": "http://spam.example"},
        )
    assert resp.status_code == 400
