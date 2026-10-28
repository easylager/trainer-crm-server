"""Админский API заявок «места от людей» (PDEC-028)."""
import time
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application import place_suggestion_use_cases as uc
from tests.api.test_city_picks_api import patch_admin_principal
from tests.shared.test_telegram_webapp import _build_signed_init_data

URL = "/api/webapp/admin/place-suggestions"
TOKEN = "123456:ADMIN-TEST"


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)
    monkeypatch.setattr(uc, "notify_author_approved", _noop)
    out: list[dict] = []

    async def _fake_send(**kw):
        out.append(kw)

    monkeypatch.setattr(uc, "send_client_plain_notification", _fake_send)
    return out


async def _suggest(db_session, *, author=None, contact=None, name="Пса-API каток") -> int:
    res = await uc.create_place_suggestion(
        db_session, source="miniapp" if author else "site", kind="ice", city_id=None,
        new_city={"name": "Пса-API-город", "country": "BY", "lat": 52.1, "lon": 23.7},
        name=name, address="ул. Тестовая, 1", details={"price_adult": "8"}, contact=contact,
        author_telegram_id=author, client_ip=None,
    )
    return int(res["id"])


@pytest.mark.asyncio
async def test_non_admin_gets_403(app_use_test_db, monkeypatch):
    monkeypatch.setattr(
        "src.api.miniapp_auth.deps.Settings",
        lambda: SimpleNamespace(telegram_bot_token_admin=TOKEN, admin_telegram_ids=[1]),
    )
    raw = _build_signed_init_data(TOKEN, user_id=999_001, auth_date=int(time.time()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(URL, headers={"X-Telegram-Init-Data": raw})
        approve = await client.post(f"{URL}/1/approve", headers={"X-Telegram-Init-Data": raw})
    assert resp.status_code == 403 and approve.status_code == 403


@pytest.mark.asyncio
async def test_full_cycle_new_message_approve(app_use_test_db, db_session, sent):
    sid = await _suggest(db_session, author=555_001)
    with patch_admin_principal(user_id=4242):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            listing = await client.get(URL, params={"tab": "new"})
            assert listing.status_code == 200, listing.text
            assert sid in [i["id"] for i in listing.json()["items"]]

            patched = await client.patch(f"{URL}/{sid}", json={"name": "Пса-API арена"})
            assert patched.status_code == 200, patched.text
            assert patched.json()["name"] == "Пса-API арена"

            msg = await client.post(f"{URL}/{sid}/messages", json={"body": "Какие часы работы?"})
            assert msg.status_code == 200, msg.text
            assert msg.json()["delivered"] is True
            assert sent and sent[0]["telegram_chat_id"] == 555_001 and "Какие часы работы?" in sent[0]["html_text"]

            waiting = await client.get(URL, params={"tab": "waiting"})
            assert sid in [i["id"] for i in waiting.json()["items"]]
            detail = await client.get(f"{URL}/{sid}")
            assert detail.json()["status"] == "needs_info"
            assert [m["direction"] for m in detail.json()["messages"]] == ["to_author"]

            approved = await client.post(f"{URL}/{sid}/approve")
            assert approved.status_code == 200, approved.text
            body = approved.json()
            assert body["url"] == f"/p/{body['url'].split('/')[2]}/{body['slug']}"
            again = await client.post(f"{URL}/{sid}/approve")
            assert again.status_code == 409

    by = (await db_session.execute(
        text("SELECT confirmed_by_admin_id, name FROM arenas WHERE id=:id"), {"id": body["arena_id"]})).one()
    assert by[0] == 4242 and by[1] == "Пса-API арена"


@pytest.mark.asyncio
async def test_message_without_telegram_author_returns_contact(app_use_test_db, db_session, sent):
    sid = await _suggest(db_session, contact="anna@example.com")
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"{URL}/{sid}/messages", json={"body": "Уточните адрес"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["delivered"] is False and resp.json()["contact"] == "anna@example.com"
    assert resp.json()["message"]["direction"] == "note" and sent == []


@pytest.mark.asyncio
async def test_reject_duplicate_and_errors(app_use_test_db, db_session):
    a = await _suggest(db_session, name="Пса-API отказ")
    b = await _suggest(db_session, name="Пса-API дубль")
    city_id = (await db_session.execute(text("SELECT id FROM cities WHERE name='Пса-API-город'"))).scalar()
    if city_id is None:
        city_id = (await db_session.execute(text(
            "INSERT INTO cities (name, sort_order, is_active, country) VALUES ('Пса-API-город', 9999, true, 'BY') "
            "RETURNING id"))).scalar_one()
    target = (await db_session.execute(text(
        "INSERT INTO arenas (city_id, name, venue_type, is_active, is_confirmed) "
        "VALUES (:c, 'Пса-API цель', 'ice', true, true) RETURNING id"), {"c": city_id})).scalar_one()
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            bad_tab = await client.get(URL, params={"tab": "all"})
            missing = await client.get(f"{URL}/99999999")
            bad_reason = await client.post(f"{URL}/{a}/reject", json={"reason": "boring"})
            ok = await client.post(f"{URL}/{a}/reject", json={"reason": "spam"})
            closed_patch = await client.patch(f"{URL}/{a}", json={"name": "X"})
            dup = await client.post(f"{URL}/{b}/duplicate", json={"target_arena_id": target,
                                                                   "copy_fields": ["visitor_prices"]})
    assert bad_tab.status_code == 400 and missing.status_code == 404 and bad_reason.status_code == 400
    assert ok.status_code == 200 and closed_patch.status_code == 409
    assert dup.status_code == 200, dup.text
    prices = (await db_session.execute(text(
        "SELECT visitor_prices FROM arena_profiles WHERE arena_id=:a"), {"a": target})).scalar()
    assert prices == {"adult": "8", "currency": "BYN", "source": "visitors"}
