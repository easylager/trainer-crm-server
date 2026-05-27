"""Sold pass price is frozen on pass_instances and survives product price edits."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.pass_product_use_cases import issue_pass_to_client
from src.application.stats_use_cases import get_trainer_revenue_breakdown_for_range
from src.application.trainer_issued_use_cases import list_trainer_issued_items

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_trainer_client(db_session: AsyncSession) -> tuple[int, int, int]:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'Sale', 'Price', :phone, :pn) RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, is_active)
            VALUES (:tid, 'Pack 8', 8, 8000, true) RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    (pass_product_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()
    return trainer_id, client_id, pass_product_id


@pytest.mark.asyncio
async def test_pass_instance_sale_price_survives_product_price_change(db_session: AsyncSession) -> None:
    trainer_id, client_id, pass_product_id = await _seed_trainer_client(db_session)

    issued = await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)
    assert issued["price_cents"] == 8000

    await db_session.execute(
        text(
            "UPDATE trainer_pass_products SET price_cents = 12000 WHERE id = :pid"
        ),
        {"pid": pass_product_id},
    )
    await db_session.commit()

    items = await list_trainer_issued_items(db_session, trainer_id, kind="pass")
    assert items["total"] == 1
    assert items["items"][0]["price_cents"] == 8000

    r = await db_session.execute(
        text("SELECT price_cents FROM pass_instances WHERE pass_product_id = :pid"),
        {"pid": pass_product_id},
    )
    assert int(r.scalar() or 0) == 8000


@pytest.mark.asyncio
async def test_revenue_breakdown_uses_frozen_pass_sale_price(db_session: AsyncSession) -> None:
    trainer_id, client_id, pass_product_id = await _seed_trainer_client(db_session)
    await issue_pass_to_client(db_session, trainer_id, client_id, pass_product_id)

    await db_session.execute(
        text("UPDATE trainer_pass_products SET price_cents = 12000 WHERE id = :pid"),
        {"pid": pass_product_id},
    )
    await db_session.commit()

    r = await db_session.execute(text("SELECT CURRENT_DATE"))
    today = r.scalar()

    breakdown = await get_trainer_revenue_breakdown_for_range(
        db_session, trainer_id, today, today
    )
    assert breakdown["revenue_pass_sales_cents"] == 8000
    assert breakdown["revenue_total_cents"] == 8000
