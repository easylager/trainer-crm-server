"""Публичный API зимних точек и отметка с сайта (TASK-343: W1, W4, W5, Z1, список/сорт)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.deps import get_session
from src.application import winter_public
from tests.application.winter_helpers import make_point

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"
HDR = {"user-agent": UA, "sec-fetch-site": "same-origin"}


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "x" * 40)
    monkeypatch.setenv("YANDEX_STATIC_API_KEY", "k-test")


@pytest.fixture
async def client(db_session, app_use_test_db):
    async def _s():
        yield db_session

    app.dependency_overrides[get_session] = _s
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.pop(get_session, None)


async def city_of(db, aid):
    return (await db.execute(text("SELECT city_id FROM arenas WHERE id=:a"), {"a": aid})).scalar_one()


@pytest.mark.asyncio
async def test_flag_off_is_404(client, db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "0")
    aid = await make_point(db_session)
    assert (await client.get(f"/api/public/winter/points/{aid}")).status_code == 404


@pytest.mark.asyncio
async def test_list_sort_pin_first_then_flooded_then_distance(on, client, db_session):
    far = await make_point(db_session, name="Дальний", lat=53.95, lon=27.7, state="flooded")
    near = await make_point(db_session, name="Ближний", lat=53.9, lon=27.56, state="flooded")
    waiting = await make_point(db_session, name="Ждём", lat=53.9, lon=27.5601, state="waiting")
    pinned = await make_point(db_session, name="Немига", lat=53.8, lon=27.4, state="waiting", pin=1)
    hidden = await make_point(db_session, name="Скрыт", state="hidden")
    city = await city_of(db_session, near)
    r = await client.get(f"/api/public/winter/cities/{city}/points", params={"lat": 53.9, "lon": 27.56})
    assert r.status_code == 200
    names = [i["name"] for i in r.json()["items"]]
    assert names == ["Немига", "Ближний", "Дальний", "Ждём"]
    assert hidden not in [i["id"] for i in r.json()["items"]]
    assert r.json()["flooded"] == 2


@pytest.mark.asyncio
async def test_imprecise_point_has_no_distance_map_or_pin(on, client, db_session):
    aid = await make_point(db_session, precision="city", lat=None, lon=None)
    d = (await client.get(f"/api/public/winter/points/{aid}", params={"lat": 53.9, "lon": 27.5})).json()
    assert d["locating"] and d["distance_km"] is None and d["lat"] is None and d["static_map_url"] is None


@pytest.mark.asyncio
async def test_precise_point_has_static_map_and_no_open_now(on, client, db_session):
    aid = await make_point(db_session, hours={"weekly": {k: [["07:00", "23:00"]] for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}})
    d = (await client.get(f"/api/public/winter/points/{aid}")).json()
    assert d["static_map_url"].startswith("https://static-maps.yandex.ru/v1?") and "apikey=k-test" in d["static_map_url"]
    assert d["hours"]["label"] == "зимой 2025/26" and d["hours"]["summary"].startswith("Ежедневно")
    assert "open_now" not in d and "is_open" not in d
    assert d["mark_token"]


@pytest.mark.asyncio
async def test_unknown_hours_never_24h(on, client, db_session):
    aid = await make_point(db_session)
    d = (await client.get(f"/api/public/winter/points/{aid}")).json()
    assert d["hours"]["known"] is False and d["hours"]["fallback"] == "Часы уточняйте по телефону"


@pytest.mark.asyncio
async def test_site_mark_requires_token_origin_human_and_honeypot(on, client, db_session):
    aid = await make_point(db_session)
    tok = (await client.get(f"/api/public/winter/points/{aid}")).json()["mark_token"]
    url = f"/api/public/winter/points/{aid}/marks"
    body = {"kind": "ice", "value": "flooded", "token": tok}
    assert (await client.post(url, json={**body, "token": "1.bad"}, headers=HDR)).status_code == 403
    assert (await client.post(url, json=body, headers={"user-agent": "curl/8"})).status_code == 403
    assert (await client.post(url, json=body, headers={"user-agent": UA, "sec-fetch-site": "cross-site"})).status_code == 403
    assert (await client.post(url, json={**body, "website": "x"}, headers=HDR)).status_code == 400
    other = await make_point(db_session, name="Другая")
    assert (await client.post(f"/api/public/winter/points/{other}/marks", json=body, headers=HDR)).status_code == 403  # токен чужой точки
    ok = await client.post(url, json=body, headers=HDR)
    assert ok.status_code == 200 and ok.json()["state"] == "waiting"
    again = await client.post(url, json={**body, "value": "not_flooded"}, headers=HDR)
    assert again.status_code == 429 and "retry-after" in again.headers


@pytest.mark.asyncio
async def test_site_mark_on_hidden_point_is_404(on, client, db_session):
    aid = await make_point(db_session, state="hidden")
    tok = winter_public.make_page_token(aid, datetime.now(timezone.utc))
    r = await client.post(f"/api/public/winter/points/{aid}/marks", json={"kind": "ice", "value": "flooded", "token": tok}, headers=HDR)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_without_actor_secret_site_marks_are_off(client, db_session, monkeypatch):
    monkeypatch.setenv("SEASONAL_RINKS_ENABLED", "1")
    monkeypatch.delenv("CATALOG_ACTOR_HMAC_SECRET", raising=False)
    aid = await make_point(db_session)
    d = (await client.get(f"/api/public/winter/points/{aid}")).json()
    assert d["mark_token"] is None


def test_page_token_expiry_and_binding(monkeypatch):
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "y" * 40)
    now = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
    tok = winter_public.make_page_token(7, now)
    assert winter_public.check_page_token(7, tok, now)
    assert not winter_public.check_page_token(8, tok, now)
    from datetime import timedelta

    assert not winter_public.check_page_token(7, tok, now + timedelta(minutes=31))
    assert not winter_public.check_page_token(7, None, now)
