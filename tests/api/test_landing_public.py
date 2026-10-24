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
from src.application.trainer_start_payload import (
    TELEGRAM_START_PAYLOAD_MAX_LEN,
    TrainerStartKind,
    parse_trainer_start_payload,
    split_arena_suffix,
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


def test_deep_link_carries_the_rink_after_the_referral():
    """Каток — последним хвостом: токен и ``_ref_`` разбираются как раньше."""
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    assert (
        build_trainer_bot_deep_link("tok123", arena_id=42, settings=s)
        == "https://t.me/IceProTestBot?start=link_tok123_arena_42"
    )
    assert (
        build_trainer_bot_deep_link("tok123", referral_code="REF1", arena_id=42, settings=s)
        == "https://t.me/IceProTestBot?start=link_tok123_ref_REF1_arena_42"
    )


def test_rink_is_dropped_when_payload_would_not_fit_telegram():
    """Лимит start-параметра — 64 символа; вход и реферал важнее катка."""
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    token = "t" * 43  # длина реального token_urlsafe(32)
    with_ref = build_trainer_bot_deep_link(token, referral_code="ABCDEFGH", arena_id=123, settings=s)
    assert with_ref.endswith(f"start=link_{token}_ref_ABCDEFGH")
    plain = build_trainer_bot_deep_link(token, arena_id=123, settings=s)
    payload = plain.split("start=", 1)[1]
    assert payload.endswith("_arena_123") and len(payload) <= TELEGRAM_START_PAYLOAD_MAX_LEN


def test_start_payload_reads_the_rink():
    parsed = parse_trainer_start_payload("link_tok_x-1_ref_REF1_arena_42")
    assert parsed.kind == TrainerStartKind.LINK
    assert (parsed.link_token, parsed.ref_code, parsed.arena_id) == ("tok_x-1", "REF1", 42)
    parsed = parse_trainer_start_payload("link_tok_arena_7")
    assert (parsed.link_token, parsed.ref_code, parsed.arena_id) == ("tok", None, 7)
    assert parse_trainer_start_payload("link_tok").arena_id is None
    assert split_arena_suffix("link_tok_arena_0") == ("link_tok_arena_0", None)
    assert split_arena_suffix("link_tok_arena_x") == ("link_tok_arena_x", None)
    # Чужие payload-ы катка не несут.
    assert split_arena_suffix("col_x_arena_5") == ("col_x_arena_5", None)


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


@pytest.fixture
def _no_rink_cache():
    from src.application.trainer_landing_page import clear_rink_picker_cache_for_tests

    clear_rink_picker_cache_for_tests()
    yield
    clear_rink_picker_cache_for_tests()


@pytest.mark.asyncio
async def test_landing_trainers_renders_rink_first_page(monkeypatch, _no_rink_cache):
    """«Ученики с катка» (TASK-322): часть сайта, SEO, превью, аналитика, цены PDEC-025, HEAD."""
    s = _landing_settings(
        trainer_bot_username="IceProTestBot",
        webapp_base_url="https://glideclub.by",
        yandex_metrika_counter_id=12345,
        google_analytics_measurement_id="G-ABC1234",
    )
    monkeypatch.setattr("src.shared.config.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/trainers")
        head = await client.head("/trainers")
        cover = await client.get("/landing/og-trainers.png")
        raw = await client.get("/landing/index.html", follow_redirects=False)
    assert resp.status_code == 200
    body = resp.text
    assert body.count("<h1") == 1 and "Ваши ученики" in body
    assert "<title>CRM для тренера по фигурному катанию и хоккею — Glide</title>" in body
    assert '<link rel="canonical" href="https://glideclub.by/trainers">' in body
    assert '<meta name="robots" content="index, follow">' in body
    assert '<meta property="og:image" content="https://glideclub.by/landing/og-trainers.png">' in body
    assert '<meta name="twitter:image" content="https://glideclub.by/landing/og-trainers.png">' in body
    assert '<meta property="og:image:width" content="1200">' in body
    assert "mc.yandex.ru/metrika/tag.js?id=12345" in body
    assert "googletagmanager.com/gtag/js?id=G-ABC1234" in body
    assert '"ym_counter_id": 12345' in body
    # Кнопки — настоящие ссылки на /join: путь регистрации виден поисковику и работает без JS.
    assert body.count('js-tl-join" href="/join"') >= 3
    assert "39 BYN" in body and "105 BYN за 3 месяца" in body and "375 BYN за год" in body
    assert 'class="b-site-foot"' in body and "fonts.googleapis.com" not in body
    graph = []
    for chunk in body.split('<script type="application/ld+json">')[1:]:
        data = json.loads(chunk.split("</script>", 1)[0])
        graph.extend(data.get("@graph") or [data])
    types = {n["@type"] for n in graph}
    assert {"SoftwareApplication", "BreadcrumbList", "FAQPage"} <= types
    assert head.status_code == 200
    assert cover.status_code == 200 and cover.headers["content-type"].startswith("image/png")
    assert raw.status_code == 301 and raw.headers["location"] == "/trainers"


@pytest.mark.asyncio
async def test_landing_trainers_without_counters_has_no_analytics(monkeypatch, _no_rink_cache):
    s = _landing_settings(
        trainer_bot_username="IceProTestBot",
        yandex_metrika_counter_id=None,
        google_analytics_measurement_id=None,
    )
    monkeypatch.setattr("src.shared.config.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/trainers")).text
    assert "mc.yandex" not in body and "googletagmanager" not in body
    assert "ym_counter_id" not in body


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
async def test_trainer_join_passes_the_rink_to_the_bot(db_session, monkeypatch):
    """``/join?arena=`` с лендинга катка: каток едет в start-параметре, мусор — нет."""
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_start_max_requests=20)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False) as client:
        with_rink = await client.get("/join?arena=42&utm_source=qr")
        junk = await client.get("/join?arena=4x2")
        negative = await client.get("/join?arena=-1")
    assert with_rink.status_code == 302
    assert with_rink.headers["location"].endswith("_arena_42")
    for resp in (junk, negative):
        assert resp.status_code == 302
        assert "_arena_" not in resp.headers["location"]


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
            f"/join?utm_source=instagram&utm_medium=bio&utm_campaign={long_campaign}&from=l.instagram.com&arena=5&junk=1"
        )
    assert resp.status_code == 302
    payload = next(p for e, p in events if e == "landing.trainer_join_redirect")
    assert payload["utm_source"] == "instagram"
    assert payload["utm_medium"] == "bio"
    assert payload["utm_campaign"] == "x" * 64
    assert payload["from"] == "l.instagram.com"
    assert payload["arena"] == "5"
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
