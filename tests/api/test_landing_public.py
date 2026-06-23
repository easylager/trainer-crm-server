"""Public Ice Pro landing API and SSR entry."""
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
    assert data["brand"]["name"] == "Ice Pro"
    assert data["registration_enabled"] is True
    assert "hero" in data and "bento" in data
    assert "value_pillars" in data and len(data["value_pillars"]) == 4
    assert "activation_arc" in data and len(data["activation_arc"]) == 4
    assert data.get("sections", {}).get("bento_heading")
    assert data.get("sections", {}).get("arc_heading")
    assert data.get("sections", {}).get("steps_heading")


@pytest.mark.asyncio
async def test_landing_root_injects_config_script(monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot")
    monkeypatch.setattr("src.application.landing_manifest.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert 'data-vertical="ice"' in body
    assert 'id="landing-config"' in body
    assert "Ice Pro" in body


@pytest.mark.asyncio
async def test_trainer_start_happy_path(db_session, monkeypatch):
    s = _landing_settings(trainer_bot_username="IceProTestBot", landing_trainer_start_max_requests=20)
    monkeypatch.setattr("src.api.routes.public.Settings", lambda: s)
    monkeypatch.setattr("src.application.landing_trainer_start_use_cases.Settings", lambda: s)
    monkeypatch.setattr("src.application.trainer_link_token_use_cases.Settings", lambda: s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/public/trainer-start",
            json={"referral_code": "REF9"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["trainer_id"] > 0
    assert data["redirect_url"].startswith("https://t.me/IceProTestBot?start=link_")
    assert "_ref_REF9" in data["redirect_url"]

    row = await db_session.execute(
        text("SELECT 1 FROM trainer_link_tokens WHERE trainer_id = :tid"),
        {"tid": data["trainer_id"]},
    )
    assert row.fetchone() is not None


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
