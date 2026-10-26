"""Пользователь каталога: есть ``client_sessions``, нет строки ``clients``, регистрации нет.

Раньше его действия упирались в «завершите регистрацию» / 403 «Client not found» — шаг,
которого для него не существует (обращение #13). Записи заводят клиента на месте,
снятия отметок без клиента — пустая операция, экраны открываются без ошибки.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch
from urllib.parse import quote

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_client_miniapp_integration import patch_client_init_auth

_INIT_DATA = "user=" + quote('{"id":1,"first_name":"Аня","last_name":"Каток","username":"anya_ice"}') + "&hash=x"
_HEADERS = {"X-Telegram-Init-Data": _INIT_DATA}


def _fresh_tid() -> int:
    return 7_700_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _catalog_only(db_session) -> int:
    tid = _fresh_tid()
    await db_session.execute(
        text("INSERT INTO client_sessions (telegram_id, state) VALUES (:tid, 'city_selected')"),
        {"tid": tid},
    )
    await db_session.commit()
    return tid


async def _trainer(db_session) -> int:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = int(r.scalar_one())
    await db_session.commit()
    return trainer_id


async def _client_row(db_session, tid: int):
    r = await db_session.execute(
        text("SELECT id, first_name, last_name FROM clients WHERE telegram_id = :tid"), {"tid": tid}
    )
    return r.fetchall()


def _api() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/webapp/client/trainer-edges/save", "/api/webapp/client/trainer-edges/notify-slots"])
async def test_trainer_edge_write_creates_client_with_telegram_name(app_use_test_db, db_session, path) -> None:
    tid = await _catalog_only(db_session)
    trainer_id = await _trainer(db_session)
    with patch_client_init_auth(tid):
        async with _api() as client:
            r = await client.post(path, json={"trainer_id": trainer_id}, headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["edge"] is not None
    rows = await _client_row(db_session, tid)
    assert len(rows) == 1
    assert (rows[0][1], rows[0][2]) == ("Аня", "Каток")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/webapp/client/trainer-edges/save/{trainer_id}", {"edge": None}),
        ("/api/webapp/client/trainer-edges/notify-slots/{trainer_id}", {"edge": None}),
        ("/api/webapp/client/trainer-edges/primary", {"success": True}),
        ("/api/webapp/client/watches/trainer-slots/{trainer_id}", {"success": True}),
    ],
)
async def test_unmark_without_client_is_a_noop(app_use_test_db, db_session, path, expected) -> None:
    tid = await _catalog_only(db_session)
    trainer_id = await _trainer(db_session)
    with patch_client_init_auth(tid):
        async with _api() as client:
            r = await client.delete(path.format(trainer_id=trainer_id), headers=_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json() == expected
    assert await _client_row(db_session, tid) == []


@pytest.mark.asyncio
async def test_ice_watch_delete_without_client_is_not_found(app_use_test_db, db_session) -> None:
    tid = await _catalog_only(db_session)
    with patch_client_init_auth(tid):
        async with _api() as client:
            r = await client.delete("/api/webapp/client/ice-watches/999999", headers=_HEADERS)
    assert r.status_code == 404
    assert "регистрац" not in r.text


@pytest.mark.asyncio
async def test_certificate_activate_reaches_code_check_without_client(app_use_test_db, db_session) -> None:
    """Раньше 403 «Client not found» до проверки кода; теперь клиент заводится, неверный код — 404."""
    tid = await _catalog_only(db_session)
    with patch_client_init_auth(tid):
        async with _api() as client:
            r = await client.post(
                "/api/webapp/client/certificates/activate", json={"code": "NO-SUCH-CODE"}, headers=_HEADERS
            )
    assert r.status_code == 404, r.text
    assert len(await _client_row(db_session, tid)) == 1


@pytest.mark.asyncio
async def test_group_join_request_creates_client(app_use_test_db, db_session) -> None:
    tid = await _catalog_only(db_session)
    with patch("src.api.routes.webapp_training_groups._client_tid", return_value=tid):
        async with _api() as client:
            r = await client.post("/api/webapp/client/training-groups/999999/join-request", headers=_HEADERS)
    assert r.status_code != 403, r.text
    assert "Client profile required" not in r.text
    assert len(await _client_row(db_session, tid)) == 1


@pytest.mark.asyncio
async def test_family_access_screen_opens_and_invite_explains_trainer_link(app_use_test_db, db_session) -> None:
    tid = await _catalog_only(db_session)
    with patch_client_init_auth(tid):
        async with _api() as client:
            screen = await client.get("/api/webapp/client/family-access", headers=_HEADERS)
            invite = await client.post("/api/webapp/client/family-access/invite", headers=_HEADERS)
    assert screen.status_code == 200, screen.text
    assert screen.json()["members"] == []
    assert invite.status_code == 400
    assert "запишитесь к тренеру" in invite.json()["detail"]
    assert "регистрац" not in invite.text
    assert await _client_row(db_session, tid) == []
