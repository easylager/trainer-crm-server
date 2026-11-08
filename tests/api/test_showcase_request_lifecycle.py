"""Полный путь заявки с витрины: клиент → очередь DM → тренер отвечает → клиент видит ответ."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.client_request_use_cases import get_pending_request_notifications, get_pending_response_notifications
from src.bot.notification_loops import process_request_notifications_batch
from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _trainer_on
from tests.api.test_webapp_client_miniapp_integration import (
    _fresh_client_telegram_id,
    patch_client_init_auth,
)
from tests.api.test_webapp_trainer_schedule_integration import (
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)
from tests.conftest import belarus_test_phone


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_showcase_personalized_request_full_lifecycle(app_use_test_db, db_session, monkeypatch) -> None:
    """Как с карточки витрины без окон: POST с trainer_id → DM-очередь → respond → список клиента."""
    async with _client() as http:
        place = await _place(db_session)
        trainer_id = await _trainer_on(db_session, http, place, first_name="ЖизньЗаявки")

    trainer_tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :t"),
        {"tg": trainer_tg, "t": trainer_id},
    )
    service_id = (
        await db_session.execute(
            text("SELECT service_id FROM trainer_services WHERE trainer_id = :t LIMIT 1"),
            {"t": trainer_id},
        )
    ).scalar_one()
    await db_session.commit()

    client_tg = _fresh_client_telegram_id()
    phone, _ = belarus_test_phone(client_tg)
    headers_c = {"X-Telegram-Init-Data": "mock"}

    # 1) Клиент оставляет заявку (тело как у trainer-showcase-main.js sendRequest).
    with patch_client_init_auth(client_tg):
        async with _client() as http:
            created = await http.post(
                "/api/webapp/client/request",
                json={
                    "city_id": place["city_id"],
                    "service_id": int(service_id),
                    "trainer_id": trainer_id,
                    "comment": "дочь, выходные утром",
                    "first_name": "Анна",
                    "phone": phone,
                },
                headers=headers_c,
            )
            assert created.status_code == 200, created.text
            rid = int(created.json()["request_id"])

            listed = await http.get("/api/webapp/client/requests", headers=headers_c)
            item = next(x for x in listed.json()["items"] if x["id"] == rid)
            assert item["is_personalized"] is True
            assert item["trainer_id"] == trainer_id
            assert item.get("responses") in (None, [])

    # 2) API сразу DM не шлёт — только notification_service.
    n0 = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM client_request_notifications WHERE client_request_id = :r"),
            {"r": rid},
        )
    ).scalar_one()
    assert int(n0) == 0

    pending = await get_pending_request_notifications(db_session)
    hit = next((p for p in pending if p["request_id"] == rid and p["trainer_id"] == trainer_id), None)
    assert hit is not None
    assert hit["trainer_telegram_id"] == trainer_tg

    # Тест про путь заявки, а не про тихие часы: иначе падает в CI после 22:00 по Минску.
    monkeypatch.setattr(
        "src.bot.notification_loops.is_trainer_push_allowed_now", AsyncMock(return_value=True)
    )
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    await process_request_notifications_batch(bot, db_session)
    bot.send_message.assert_awaited()
    n1 = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM client_request_notifications "
                "WHERE client_request_id = :r AND trainer_id = :t"
            ),
            {"r": rid, "t": trainer_id},
        )
    ).scalar_one()
    assert int(n1) == 1

    # 3) Тренер видит заявку и отвечает.
    with patch_trainer_webapp_init(trainer_tg):
        async with _client() as http:
            headers_t = {"X-Telegram-Init-Data": "mock"}
            summary = await http.get("/api/webapp/trainer/requests/summary", headers=headers_t)
            assert summary.status_code == 200
            assert summary.json()["unanswered_count"] >= 1

            inbox = await http.get("/api/webapp/trainer/requests", headers=headers_t)
            assert inbox.status_code == 200
            row = next(x for x in inbox.json()["items"] if x["id"] == rid)
            assert row["is_personalized"] is True
            assert row["has_responded"] is False

            answered = await http.post(
                f"/api/webapp/trainer/requests/{rid}/respond",
                json={"trainer_comment": "Напишите в Telegram — подберём время"},
                headers=headers_t,
            )
            assert answered.status_code == 200, answered.text
            assert answered.json()["success"] is True

            summary2 = await http.get("/api/webapp/trainer/requests/summary", headers=headers_t)
            # После ответа эта заявка больше не в «неотвеченных».
            assert summary2.json()["unanswered_count"] == summary.json()["unanswered_count"] - 1

    # 4) Клиент видит ответ; очередь уведомления клиенту готова.
    with patch_client_init_auth(client_tg):
        async with _client() as http:
            listed2 = await http.get("/api/webapp/client/requests", headers=headers_c)
            item2 = next(x for x in listed2.json()["items"] if x["id"] == rid)
            responses = item2.get("responses") or []
            assert len(responses) == 1
            assert responses[0]["trainer_id"] == trainer_id
            assert "подберём" in (responses[0].get("trainer_comment") or "")

    pending_client = await get_pending_response_notifications(db_session)
    assert any(p["request_id"] == rid and p["client_telegram_id"] == client_tg for p in pending_client)
