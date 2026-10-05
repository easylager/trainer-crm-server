"""
Хаб клиента: сертификаты приезжают вместе с bootstrap.

Продуктовое правило (TASK-161): на Главной показываем только то, чем клиент прямо сейчас
может заплатить — активированный им сертификат с ненулевым остатком. Выданный, но не
активированный (`status='issued'`) — ещё не его баланс. Код сертификата наружу не отдаём:
хабу он не нужен, а это платёжный секрет.

Харнесс: coros внутри `asyncio.gather` у bootstrap открывают свои сессии и не видят
транзакцию теста (см. докстринг `tests/conftest.py` и комментарий в
`tests/api/test_webapp_trainer_lifecycle.py`). Поэтому здесь подменяется **только сессия**
— сам резолв действующего профиля и SQL сертификатов остаются настоящими.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.certificate_use_cases import list_client_certificate_instances
from src.application.client_profile_use_cases import resolve_acting_client_id
from tests.api.test_webapp_client_miniapp_integration import (
    _client_auth_headers,
    patch_client_init_auth,
)


def _fresh_client_telegram_id() -> int:
    return 7_830_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _insert_trainer(db_session, *, first_name: str = "Иван", last_name: str = "Тренеров") -> int:
    """Тренер с профилем: сертификату нужно только имя выдавшего, без арен и услуг."""
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age)
            VALUES (:tid, :fn, :ln, 30)
            """
        ),
        {"tid": trainer_id, "fn": first_name, "ln": last_name},
    )
    await db_session.commit()
    return trainer_id


async def _insert_client(db_session, *, telegram_id: int | None, first_name: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES (:fn, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()
    return client_id


async def _add_child_profile(client, *, first_name: str) -> int:
    r = await client.post(
        "/api/webapp/client/profiles",
        json={"first_name": first_name},
        headers=_client_auth_headers(),
    )
    assert r.status_code == 200, r.text
    return int(r.json()["client_id"])


async def _issue_certificate(
    db_session,
    *,
    trainer_id: int,
    activated_client_id: int,
    status: str,
    amount_cents: int = 10000,
    amount_remaining_cents: int = 10000,
) -> tuple[int, str]:
    """Сертификат прямо в БД. Возвращает (id, code)."""
    code = f"CERT-{uuid.uuid4().hex[:10].upper()}"
    r = await db_session.execute(
        text(
            """
            INSERT INTO certificate_instances (
                trainer_id, recipient_name, amount_cents, amount_remaining_cents,
                code, status, activated_client_id
            )
            VALUES (:tid, 'Подарок', :amt, :rem, :code, :st, :cid)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "amt": amount_cents,
            "rem": amount_remaining_cents,
            "code": code,
            "st": status,
            "cid": activated_client_id,
        },
    )
    cert_id = int(r.scalar_one())
    await db_session.commit()
    return cert_id, code


@contextlib.asynccontextmanager
async def _bootstrap_reads_test_session(db_session, *, certificates_error: BaseException | None = None):
    """Читать bootstrap'ом данные теста: та же логика, но на сессии теста.

    Доступ сериализован — все coros bootstrap дёргают резолв профиля одновременно, а
    asyncpg не допускает параллельных запросов в одном соединении.
    """
    lock = asyncio.Lock()

    async def _resolve(_s, account_telegram_id, requested_profile_id=None):
        async with lock:
            return await resolve_acting_client_id(
                db_session, account_telegram_id, requested_profile_id
            )

    async def _certificates(_s, client_id):
        if certificates_error is not None:
            raise certificates_error
        async with lock:
            return await list_client_certificate_instances(db_session, client_id)

    with patch(
        "src.api.routes.webapp.resolve_acting_client_id", side_effect=_resolve
    ), patch(
        "src.api.routes.webapp.list_client_certificate_instances", side_effect=_certificates
    ):
        yield


async def _bootstrap_response(telegram_id: int, *, profile_id: int | None = None):
    headers = dict(_client_auth_headers())
    if profile_id is not None:
        headers["X-Profile-Id"] = str(profile_id)
    with patch_client_init_auth(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/api/webapp/client/hub/bootstrap", headers=headers)


async def _bootstrap(telegram_id: int, *, profile_id: int | None = None) -> dict:
    r = await _bootstrap_response(telegram_id, profile_id=profile_id)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_activated_certificate_with_balance_in_bootstrap(app_use_test_db, db_session) -> None:
    """Активированный сертификат с остатком приходит в `certificates` рядом с `passes`."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")
    cert_id, _code = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=client_id,
        status="activated",
        amount_cents=10000,
        amount_remaining_cents=6000,
    )

    async with _bootstrap_reads_test_session(db_session):
        body = await _bootstrap(tid)

    assert "passes" in body
    certs = body.get("certificates")
    assert isinstance(certs, list)
    row = next((c for c in certs if c["id"] == cert_id), None)
    assert row is not None, certs
    assert row["trainer_id"] == trainer_id
    assert row["trainer_name"] == "Иван Тренеров"
    assert row["amount_remaining_cents"] == 6000
    assert row["amount_cents"] == 10000
    assert row["status"] == "activated"


@pytest.mark.asyncio
async def test_issued_certificate_not_in_bootstrap(app_use_test_db, db_session) -> None:
    """`issued` — сертификат выдан, но этим клиентом не активирован: в хаб не попадает."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")
    cert_id, _code = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=client_id,
        status="issued",
    )

    async with _bootstrap_reads_test_session(db_session):
        body = await _bootstrap(tid)

    assert [c for c in body["certificates"] if c["id"] == cert_id] == []


@pytest.mark.asyncio
async def test_activated_certificate_with_zero_balance_not_in_bootstrap(
    app_use_test_db, db_session
) -> None:
    """Остаток израсходован — платить нечем, в хабе такому сертификату не место."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")
    cert_id, _code = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=client_id,
        status="activated",
        amount_cents=10000,
        amount_remaining_cents=0,
    )

    async with _bootstrap_reads_test_session(db_session):
        body = await _bootstrap(tid)

    assert [c for c in body["certificates"] if c["id"] == cert_id] == []


@pytest.mark.asyncio
async def test_bootstrap_certificates_never_expose_code(app_use_test_db, db_session) -> None:
    """Код сертификата — платёжный секрет: ни в поле `code`, ни где-либо в ответе."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")
    cert_id, code = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=client_id,
        status="activated",
        amount_remaining_cents=5000,
    )

    async with _bootstrap_reads_test_session(db_session):
        r = await _bootstrap_response(tid)

    assert r.status_code == 200, r.text
    row = next(c for c in r.json()["certificates"] if c["id"] == cert_id)
    assert "code" not in row
    assert set(row.keys()) == {
        "id",
        "trainer_id",
        "trainer_name",
        "amount_remaining_cents",
        "amount_cents",
        "status",
    }
    assert code not in r.text


@pytest.mark.asyncio
async def test_bootstrap_certificates_follow_acting_profile(app_use_test_db, db_session) -> None:
    """Сертификаты резолвятся через действующий профиль (X-Profile-Id), как и passes."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    parent_id = await _insert_client(db_session, telegram_id=tid, first_name="Мама")

    with patch_client_init_auth(tid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            child_id = await _add_child_profile(client, first_name="Лера")

    parent_cert_id, _ = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=parent_id,
        status="activated",
        amount_remaining_cents=4000,
    )
    child_cert_id, _ = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=child_id,
        status="activated",
        amount_remaining_cents=7000,
    )

    async with _bootstrap_reads_test_session(db_session):
        child_body = await _bootstrap(tid, profile_id=child_id)
        parent_body = await _bootstrap(tid)

    child_ids = {c["id"] for c in child_body["certificates"]}
    parent_ids = {c["id"] for c in parent_body["certificates"]}
    assert child_cert_id in child_ids and parent_cert_id not in child_ids
    assert parent_cert_id in parent_ids and child_cert_id not in parent_ids


@pytest.mark.asyncio
async def test_bootstrap_survives_certificate_read_failure(app_use_test_db, db_session) -> None:
    """Сбой чтения сертификатов не роняет хаб — `certificates` просто пустой."""
    trainer_id = await _insert_trainer(db_session)
    tid = _fresh_client_telegram_id()
    client_id = await _insert_client(db_session, telegram_id=tid, first_name="Клиент")
    cert_id, _code = await _issue_certificate(
        db_session,
        trainer_id=trainer_id,
        activated_client_id=client_id,
        status="activated",
        amount_remaining_cents=5000,
    )

    # Контроль: без сбоя этот сертификат в ответе есть — значит дальше падает именно чтение.
    async with _bootstrap_reads_test_session(db_session):
        ok_body = await _bootstrap(tid)
    assert [c for c in ok_body["certificates"] if c["id"] == cert_id]

    async with _bootstrap_reads_test_session(
        db_session, certificates_error=RuntimeError("certificates down")
    ):
        body = await _bootstrap(tid)

    assert body["certificates"] == []
    assert "bookings" in body and "requests" in body
