import random
import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application import place_suggestion_use_cases as uc

URL = "/api/public/place-suggestions"


async def _noop():
    return None


@pytest.fixture(autouse=True)
def _no_admin_push(monkeypatch):
    """Не слать реальные уведомления админу: .env держит боевой токен админ-бота."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", lambda sid: _noop())


def _ip() -> str:
    # Публичный адрес: приватные/документационные XFF-записи client_ip отбрасывает.
    return f"31.{random.randint(1, 250)}.{random.randint(1, 250)}.{random.randint(1, 250)}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _body(**over):
    body = {
        "kind": "ice",
        "new_city": {"name": "Пситест-Уфа", "country": "RU", "region": "Башкортостан", "lat": 54.7, "lon": 55.9},
        "name": "Ледовая арена",
        "details": {"price_adult": "500"},
        "contact": "@anna_skate",
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_post_creates_suggestion_with_telegram_link(app_use_test_db, db_session, monkeypatch):
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    async with _client() as client:
        resp = await client.post(URL, json=_body(), headers={"X-Forwarded-For": _ip()})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True and data["id"]
    assert data["telegram_link"].startswith("https://t.me/glide_test_bot?start=sg_")
    assert resp.headers["cache-control"] == "no-store"
    row = (await db_session.execute(
        text("SELECT source, new_city_name, author_telegram_id, bind_token FROM place_suggestions WHERE id=:id"),
        {"id": data["id"]},
    )).one()
    assert row[0] == "site" and row[1] == "Пситест-Уфа" and row[2] is None
    assert data["telegram_link"].endswith(f"sg_{row[3]}")


@pytest.mark.asyncio
async def test_honeypot_is_rejected(app_use_test_db, db_session):
    async with _client() as client:
        resp = await client.post(URL, json=_body(website="http://spam"), headers={"X-Forwarded-For": _ip()})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_empty_name_is_422_in_russian(app_use_test_db, db_session):
    async with _client() as client:
        resp = await client.post(URL, json=_body(name="   "), headers={"X-Forwarded-For": _ip()})
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Напишите название или пару слов о месте."


@pytest.mark.asyncio
async def test_eleventh_post_from_one_ip_is_429(app_use_test_db, db_session):
    ip = _ip()
    async with _client() as client:
        codes = [
            (await client.post(URL, json=_body(), headers={"X-Forwarded-For": ip})).status_code
            for _ in range(11)
        ]
    assert codes[:10] == [200] * 10
    assert codes[10] == 429


@pytest.mark.asyncio
async def test_city_search_endpoint(app_use_test_db, db_session, monkeypatch):
    from src.application import place_suggestion_city_search as cs

    # Ответ Nominatim уже в кэше процесса — сеть не трогаем.
    geo = [{"city_id": None, "name": "Пситестоуфа", "region": None, "country": "RU",
            "lat": 1.0, "lon": 2.0, "is_new": True}]
    monkeypatch.setitem(cs._cache, "пситестоуфа", (time.monotonic(), geo))
    async with _client() as client:
        resp = await client.get(f"{URL}/cities", params={"q": "Пситестоуфа", "geo": "1"}, headers={"X-Forwarded-For": _ip()})
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    assert resp.json()["items"][-1]["name"] == "Пситестоуфа"
