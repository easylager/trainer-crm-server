import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application import place_suggestion_use_cases as uc
from tests.shared.test_telegram_webapp import _build_signed_init_data

URL = "/api/webapp/place-suggestions"
TOKEN = "123456:ABC-DEF"


async def _noop():
    return None


@pytest.fixture(autouse=True)
def _no_admin_push(monkeypatch):
    """Не слать реальные уведомления админу: .env держит боевой токен админ-бота."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", lambda sid: _noop())


class _ClientBot:
    def __init__(self, token: str) -> None:
        self.telegram_bot_token_client = token
        self.vk_mini_app_protected_key = ""


def _body():
    return {
        "kind": "shop",
        "new_city": {"name": "Пситест-Гомель-мини", "country": "BY"},
        "name": "Заточка у арены",
        "details": {"services": ["sharpening"]},
    }


async def _row(db_session, sid: int):
    return (await db_session.execute(
        text("SELECT source, author_telegram_id, bind_token FROM place_suggestions WHERE id=:id"), {"id": sid}
    )).one()


@pytest.mark.asyncio
async def test_signed_init_data_records_author(app_use_test_db, db_session, monkeypatch):
    monkeypatch.setattr("src.api.miniapp_auth.deps.Settings", lambda: _ClientBot(TOKEN))
    raw = _build_signed_init_data(TOKEN, user_id=424243, auth_date=int(time.time()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(URL, json=_body(), headers={"X-Telegram-Init-Data": raw})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
    row = await _row(db_session, resp.json()["id"])
    assert row[0] == "miniapp" and row[1] == 424243 and row[2] is None


@pytest.mark.asyncio
async def test_without_init_data_is_accepted_without_author(app_use_test_db, db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(URL, json=_body())
    assert resp.status_code == 200, resp.text
    row = await _row(db_session, resp.json()["id"])
    assert row[0] == "miniapp" and row[1] is None


@pytest.mark.asyncio
async def test_validation_error_is_422_in_russian(app_use_test_db, db_session):
    body = _body() | {"kind": "pool"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(URL, json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Выберите, что это за место."
