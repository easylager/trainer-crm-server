"""GET /trainer/requests/summary — lightweight unanswered count for trainer hub."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)


async def _fresh_client_id(db_session) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name)
            VALUES (:tg, 'Req', 'Client')
            RETURNING id
            """
        ),
        {"tg": 7_000_000_000 + (uuid.uuid4().int % 1_000_000_000)},
    )
    cid = r.scalar_one()
    await db_session.commit()
    return int(cid)


@pytest.mark.asyncio
async def test_trainer_requests_summary_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/requests/summary")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_trainer_requests_summary_zero(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=False)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/requests/summary",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"unanswered_count": 0}


@pytest.mark.asyncio
async def test_trainer_requests_summary_personalized_unanswered(app_use_test_db, db_session) -> None:
    """Personalized request (r.trainer_id set) without response counts as 1."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    city_id = r.scalar_one()
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    service_id = r.scalar_one()
    client_id = await _fresh_client_id(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO client_requests
                (client_id, city_id, service_id, status, trainer_id, comment)
            VALUES
                (:cid, :city_id, :service_id, 'new', :tid, 'hub summary test')
            """
        ),
        {"cid": client_id, "city_id": city_id, "service_id": service_id, "tid": trainer_id},
    )
    await db_session.commit()

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/requests/summary",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"unanswered_count": 1}
