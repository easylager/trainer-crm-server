"""
Live reproduction of TASK-142/EDGE-003: on 2026-09-29 a client's certificate-order
request (personal client_requests row, trainer_id set) never got a single delivery
attempt logged — client_request_notifications stayed empty even though the request's
status was 'new' the whole time. Quiet hours and a crashing loop were ruled out by
reading prod logs/DB (see TASK-142.md); a coincident, separate SMTP network failure
(EDGE-004) hinted at a broader outbound-network problem in that window.

This test runs the exact same request shape — created via
submit_certificate_product_order_request(), the real production code path, not a
hand-built row — through process_request_notifications_batch() with a mocked bot.
If it delivers cleanly here, the query/claim pipeline itself is not the bug; the
incident is best explained by the transient network window, not a reproducible code
defect.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text

from src.application.certificate_use_cases import create_certificate_product
from src.application.client_cert_order_use_cases import (
    submit_certificate_product_order_request,
)
from src.bot.notification_loops import process_request_notifications_batch
from tests.application.test_client_cert_order_optional_name import (
    _setup_client_with_primary_trainer,
)


@pytest.mark.asyncio
async def test_cert_order_request_is_delivered_like_a_normal_request(db_session) -> None:
    telegram_id, client_id, trainer_id = await _setup_client_with_primary_trainer(db_session)
    # Give the trainer a real telegram_id — get_pending_request_notifications requires
    # t.telegram_id IS NOT NULL to pick up a personal request at all.
    trainer_tid = 950_000_000 + trainer_id
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": trainer_tid, "id": trainer_id},
    )
    await db_session.commit()

    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=5000
    )
    result = await submit_certificate_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        certificate_product_id=product_id,
        recipient_email="client@example.com",
        recipient_name="Соча",
    )
    assert result["ok"] is True
    request_id = result["request_id"]

    r = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM client_request_notifications "
            "WHERE client_request_id = :rid AND trainer_id = :tid"
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    assert r.scalar() == 0  # nothing claimed yet — matches request #12 right after creation

    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=None)
    await process_request_notifications_batch(bot, db_session)

    bot.send_message.assert_awaited_once()
    r2 = await db_session.execute(
        text(
            "SELECT COUNT(*) FROM client_request_notifications "
            "WHERE client_request_id = :rid AND trainer_id = :tid"
        ),
        {"rid": request_id, "tid": trainer_id},
    )
    assert r2.scalar() == 1
