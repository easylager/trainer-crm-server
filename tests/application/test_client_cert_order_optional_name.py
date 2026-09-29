"""Client certificate order: «Имя получателя» is optional (TASK-142/AC-004, Q-005).

submit_certificate_product_order_request used to reject an empty recipient_name
outright; now it's accepted, and when empty the "Получатель: …" line is omitted
entirely from both the request text and the trainer's push notification — not
shown with a placeholder.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import create_certificate_product
from src.application.client_cert_order_use_cases import (
    submit_certificate_product_order_request,
)
from src.bot.notification_loops import build_cert_order_trainer_notification


async def _setup_client_with_primary_trainer(db_session: AsyncSession) -> tuple[int, int, int]:
    """Returns (telegram_id, client_id, trainer_id) with a resolvable primary trainer."""
    # push_notification_start_hour/end_hour = 0/24: a trainer with no explicit window
    # falls back to a default quiet-hours window — callers that push through
    # process_request_notifications_batch (see test_request_notifier_cert_order_reproduction.py)
    # must not depend on the real wall-clock time this test happens to run at.
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, push_notification_start_hour, push_notification_end_hour) "
            "VALUES ('active', 0, 24) RETURNING id"
        )
    )
    trainer_id = int(r.scalar_one())

    r = await db_session.execute(
        text("INSERT INTO cities (name, country, price_group) VALUES ('Тестгород', 'BY', 'BY_BASE') RETURNING id")
    )
    city_id = int(r.scalar_one())
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:tid, :cid) "
            "ON CONFLICT (trainer_id) DO UPDATE SET city_id = :cid"
        ),
        {"tid": trainer_id, "cid": city_id},
    )

    r = await db_session.execute(text("INSERT INTO services (name) VALUES ('Тест') RETURNING id"))
    service_id = int(r.scalar_one())
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"),
        {"tid": trainer_id, "sid": service_id},
    )

    telegram_id = 900_000_000 + trainer_id
    r = await db_session.execute(
        text("INSERT INTO clients (telegram_id) VALUES (:tid) RETURNING id"),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())

    await db_session.execute(
        text(
            "INSERT INTO client_sessions (telegram_id, state, selected_trainer_id) "
            "VALUES (:tid, 'idle', :trainer_id) "
            "ON CONFLICT (telegram_id) DO UPDATE SET selected_trainer_id = :trainer_id"
        ),
        {"tid": telegram_id, "trainer_id": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO client_trainer_edges (client_id, telegram_id, trainer_id) "
            "VALUES (:cid, :tid, :trainer_id)"
        ),
        {"cid": client_id, "tid": telegram_id, "trainer_id": trainer_id},
    )
    await db_session.commit()
    return telegram_id, client_id, trainer_id


@pytest.mark.asyncio
async def test_submit_cert_order_request_allows_empty_recipient_name(
    db_session: AsyncSession,
) -> None:
    telegram_id, client_id, trainer_id = await _setup_client_with_primary_trainer(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )

    result = await submit_certificate_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        certificate_product_id=product_id,
        recipient_email="client@example.com",
        recipient_name="",
    )
    assert result["ok"] is True

    r = await db_session.execute(
        text("SELECT comment FROM client_requests WHERE id = :id"),
        {"id": result["request_id"]},
    )
    comment = r.scalar_one()
    assert "Получатель" not in comment


@pytest.mark.asyncio
async def test_submit_cert_order_request_includes_recipient_line_when_named(
    db_session: AsyncSession,
) -> None:
    telegram_id, client_id, trainer_id = await _setup_client_with_primary_trainer(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
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

    r = await db_session.execute(
        text("SELECT comment FROM client_requests WHERE id = :id"),
        {"id": result["request_id"]},
    )
    comment = r.scalar_one()
    assert "Получатель: Соча." in comment


@pytest.mark.asyncio
async def test_trainer_notification_omits_recipient_line_when_name_empty(
    db_session: AsyncSession,
) -> None:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    await db_session.commit()

    p = {"trainer_id": trainer_id, "client_first_name": "Иван", "request_id": 1}
    cert_meta = {"recipient_email": "client@example.com", "recipient_name": ""}
    text_out, _kb = await build_cert_order_trainer_notification(
        db_session, p=p, certificate_product_id=product_id, cert_meta=cert_meta
    )
    assert "Получатель" not in text_out


@pytest.mark.asyncio
async def test_trainer_notification_includes_recipient_line_when_named(
    db_session: AsyncSession,
) -> None:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    await db_session.commit()

    p = {"trainer_id": trainer_id, "client_first_name": "Иван", "request_id": 1}
    cert_meta = {"recipient_email": "client@example.com", "recipient_name": "Соча"}
    text_out, _kb = await build_cert_order_trainer_notification(
        db_session, p=p, certificate_product_id=product_id, cert_meta=cert_meta
    )
    assert "Получатель" in text_out
    assert "Соча" in text_out
