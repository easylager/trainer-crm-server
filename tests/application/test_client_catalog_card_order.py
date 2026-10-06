"""Catalog card orders name the trainer on the card, not only the primary trainer."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import create_certificate_product
from src.application.client_cert_order_use_cases import submit_certificate_product_order_request
from src.application.client_pass_order_use_cases import submit_pass_product_order_request
from src.application.client_request_use_cases import (
    create_client_request,
    list_my_requests_with_responses,
)
from src.application.pass_product_use_cases import create_pass_product, issue_pass_to_client
from src.bot.notification_loops import _build_pass_order_notification


async def _insert_trainer(
    db: AsyncSession,
    *,
    status: str = "active",
    with_city: bool = True,
    with_service: bool = True,
) -> int:
    r = await db.execute(
        text(
            "INSERT INTO trainers (status, push_notification_start_hour, push_notification_end_hour) "
            "VALUES (:st, 0, 24) RETURNING id"
        ),
        {"st": status},
    )
    trainer_id = int(r.scalar_one())
    if with_city:
        r = await db.execute(
            text(
                "INSERT INTO cities (name, country, price_group) "
                "VALUES (:name, 'BY', 'BY_BASE') RETURNING id"
            ),
            {"name": f"Карточка {trainer_id}"},
        )
        city_id = int(r.scalar_one())
        await db.execute(
            text("INSERT INTO trainer_profiles (trainer_id, city_id) VALUES (:tid, :cid)"),
            {"tid": trainer_id, "cid": city_id},
        )
    if with_service:
        r = await db.execute(
            text("INSERT INTO services (name) VALUES (:name) RETURNING id"),
            {"name": f"Услуга {trainer_id}"},
        )
        service_id = int(r.scalar_one())
        await db.execute(
            text(
                "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
                "VALUES (:tid, :sid, 5000)"
            ),
            {"tid": trainer_id, "sid": service_id},
        )
    return trainer_id


async def _insert_client_with_primary(db: AsyncSession, primary_trainer_id: int) -> tuple[int, int]:
    telegram_id = 910_000_000 + int(primary_trainer_id)
    r = await db.execute(
        text("INSERT INTO clients (telegram_id) VALUES (:tid) RETURNING id"),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db.execute(
        text(
            "INSERT INTO client_sessions (telegram_id, state, selected_trainer_id) "
            "VALUES (:tid, 'idle', :trainer_id)"
        ),
        {"tid": telegram_id, "trainer_id": primary_trainer_id},
    )
    await db.execute(
        text(
            "INSERT INTO client_trainer_edges (client_id, telegram_id, trainer_id) "
            "VALUES (:cid, :tid, :trainer_id)"
        ),
        {"cid": client_id, "tid": telegram_id, "trainer_id": primary_trainer_id},
    )
    await db.commit()
    return telegram_id, client_id


@pytest.mark.asyncio
async def test_pass_order_from_card_goes_to_that_trainer_not_primary(db_session: AsyncSession) -> None:
    primary_id = await _insert_trainer(db_session)
    card_id = await _insert_trainer(db_session)
    telegram_id, client_id = await _insert_client_with_primary(db_session, primary_id)
    product_id = await create_pass_product(
        db_session, card_id, name="8 занятий", sessions_total=8, price_cents=20000
    )

    missed = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=product_id,
    )
    assert missed == {"ok": False, "error": "product_not_found"}

    result = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=product_id,
        trainer_id=card_id,
    )
    assert result["ok"] is True

    row = (
        await db_session.execute(
            text("SELECT trainer_id, comment FROM client_requests WHERE id = :id"),
            {"id": result["request_id"]},
        )
    ).one()
    assert int(row[0]) == card_id
    assert f"__PASS_ORDER__:pass_product_id={product_id}" in row[1]

    again = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=product_id,
        trainer_id=card_id,
    )
    assert again == {"ok": False, "error": "duplicate_pending"}

    await db_session.execute(
        text("UPDATE client_requests SET status = 'archived' WHERE id = :id"),
        {"id": result["request_id"]},
    )
    await db_session.commit()
    later = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=product_id,
        trainer_id=card_id,
    )
    assert later == {"ok": False, "error": "daily_limit"}


@pytest.mark.asyncio
async def test_pass_order_rejects_other_trainers_product_and_inactive_trainer(
    db_session: AsyncSession,
) -> None:
    primary_id = await _insert_trainer(db_session)
    other_id = await _insert_trainer(db_session)
    quiet_id = await _insert_trainer(db_session, status="deactivated")
    telegram_id, client_id = await _insert_client_with_primary(db_session, primary_id)
    other_product = await create_pass_product(
        db_session, other_id, name="Чужой", sessions_total=4, price_cents=10000
    )
    quiet_product = await create_pass_product(
        db_session, quiet_id, name="Скрытый", sessions_total=4, price_cents=10000
    )

    wrong_owner = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=other_product,
        trainer_id=primary_id,
    )
    assert wrong_owner == {"ok": False, "error": "product_not_found"}

    quiet = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=quiet_product,
        trainer_id=quiet_id,
    )
    assert quiet == {"ok": False, "error": "trainer_not_found"}


@pytest.mark.asyncio
async def test_pass_order_needs_city_and_service(db_session: AsyncSession) -> None:
    primary_id = await _insert_trainer(db_session)
    no_city = await _insert_trainer(db_session, with_city=False)
    no_service = await _insert_trainer(db_session, with_service=False)
    telegram_id, client_id = await _insert_client_with_primary(db_session, primary_id)
    no_city_product = await create_pass_product(
        db_session, no_city, name="Без города", sessions_total=4, price_cents=8000
    )
    no_service_product = await create_pass_product(
        db_session, no_service, name="Без услуги", sessions_total=4, price_cents=8000
    )

    missing_city = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=no_city_product,
        trainer_id=no_city,
    )
    assert missing_city == {"ok": False, "error": "trainer_city_missing"}

    missing_service = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=no_service_product,
        trainer_id=no_service,
    )
    assert missing_service == {"ok": False, "error": "trainer_service_missing"}


@pytest.mark.asyncio
async def test_cert_order_from_card_goes_to_that_trainer(db_session: AsyncSession) -> None:
    primary_id = await _insert_trainer(db_session)
    card_id = await _insert_trainer(db_session)
    telegram_id, client_id = await _insert_client_with_primary(db_session, primary_id)
    product_id = await create_certificate_product(db_session, card_id, name="Подарок", amount_cents=15000)

    result = await submit_certificate_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        certificate_product_id=product_id,
        recipient_email="gift@example.com",
        recipient_name="Соча",
        trainer_id=card_id,
    )
    assert result["ok"] is True
    row = (
        await db_session.execute(
            text("SELECT trainer_id, comment FROM client_requests WHERE id = :id"),
            {"id": result["request_id"]},
        )
    ).one()
    assert int(row[0]) == card_id
    assert "gift@example.com" in row[1]
    assert f"__CERT_ORDER__:certificate_product_id={product_id}" in row[1]


@pytest.mark.asyncio
async def test_existing_booking_and_active_pass_keep_orders_visible(
    db_session: AsyncSession,
) -> None:
    """A lesson already on the books must not hide a new pass or certificate ask."""
    trainer_id = await _insert_trainer(db_session)
    telegram_id, client_id = await _insert_client_with_primary(db_session, trainer_id)
    scope = (
        await db_session.execute(
            text(
                """
                SELECT tp.city_id, ts.service_id
                FROM trainer_profiles tp
                JOIN trainer_services ts ON ts.trainer_id = tp.trainer_id
                WHERE tp.trainer_id = :tid
                """
            ),
            {"tid": trainer_id},
        )
    ).one()
    city_id, service_id = int(scope[0]), int(scope[1])
    slot_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                    VALUES (
                        :tid,
                        (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date,
                        TIME '10:00', TIME '11:00', 'booked'
                    )
                    RETURNING id
                    """
                ),
                {"tid": trainer_id},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed')
            """
        ),
        {"sid": slot_id, "tid": trainer_id, "cid": client_id, "svc": service_id},
    )
    await db_session.commit()

    held_id = await create_pass_product(
        db_session, trainer_id, name="Уже есть", sessions_total=5, price_cents=10000
    )
    await issue_pass_to_client(db_session, trainer_id, client_id, held_id)

    asked_id = await create_pass_product(
        db_session, trainer_id, name="Ещё один", sessions_total=8, price_cents=20000
    )
    pass_order = await submit_pass_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        pass_product_id=asked_id,
        trainer_id=trainer_id,
    )
    assert pass_order["ok"] is True

    cert_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=15000
    )
    cert_order = await submit_certificate_product_order_request(
        db_session,
        client_id=client_id,
        telegram_id=telegram_id,
        certificate_product_id=cert_id,
        recipient_email="gift@example.com",
        recipient_name="",
        trainer_id=trainer_id,
    )
    assert cert_order["ok"] is True

    collective_id = await create_client_request(
        db_session,
        client_id,
        city_id,
        service_id,
        comment="__COLLECTIVE_PASS_ORDER__:collective_pass_product_id=1\n\nХочу абонемент центра",
        trainer_id=trainer_id,
    )
    plain_id = await create_client_request(
        db_session,
        client_id,
        city_id,
        service_id,
        comment="Нужен тренер на эту услугу",
        trainer_id=trainer_id,
    )

    listed = await list_my_requests_with_responses(db_session, telegram_id)
    listed_ids = {int(item["id"]) for item in listed}
    assert int(pass_order["request_id"]) in listed_ids
    assert int(cert_order["request_id"]) in listed_ids
    assert collective_id in listed_ids
    assert plain_id not in listed_ids

    statuses = (
        await db_session.execute(
            text("SELECT id, status FROM client_requests WHERE id = ANY(:ids)"),
            {
                "ids": [
                    int(pass_order["request_id"]),
                    int(cert_order["request_id"]),
                    collective_id,
                    plain_id,
                ]
            },
        )
    ).fetchall()
    by_id = {int(row[0]): row[1] for row in statuses}
    assert by_id[int(pass_order["request_id"])] == "new"
    assert by_id[int(cert_order["request_id"])] == "new"
    assert by_id[collective_id] == "new"
    assert by_id[plain_id] == "archived"

    note, _kb = await _build_pass_order_notification(
        db_session,
        p={
            "trainer_id": trainer_id,
            "client_id": client_id,
            "client_first_name": "Максим",
            "client_middle_name": "",
            "client_last_name": "",
            "service_name": "Услуга",
            "request_id": int(pass_order["request_id"]),
            "client_telegram_id": telegram_id,
        },
        pass_product_id=asked_id,
    )
    assert "уже есть активный абонемент" in note
