"""Certificate product optional description field."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import (
    create_certificate_product,
    get_certificate_product,
    list_certificate_products,
    update_certificate_product,
)


async def _trainer_id(db_session: AsyncSession) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_certificate_product_description_roundtrip(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)

    product_id = await create_certificate_product(
        db_session,
        trainer_id,
        name="Подарок на день рождения",
        description="  Действует на любые занятия  ",
        amount_cents=15000,
    )
    row = await get_certificate_product(db_session, product_id, trainer_id)
    assert row is not None
    assert row["name"] == "Подарок на день рождения"
    assert row["description"] == "Действует на любые занятия"

    items = await list_certificate_products(db_session, trainer_id)
    assert any(
        i["id"] == product_id and i["description"] == row["description"] for i in items
    )

    ok = await update_certificate_product(
        db_session,
        product_id,
        trainer_id,
        description="",
    )
    assert ok
    cleared = await get_certificate_product(db_session, product_id, trainer_id)
    assert cleared is not None
    assert cleared["description"] is None


@pytest.mark.asyncio
async def test_certificate_product_default_name_without_title(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)

    product_id = await create_certificate_product(
        db_session,
        trainer_id,
        name=None,
        description=None,
        amount_cents=10000,
    )
    row = await get_certificate_product(db_session, product_id, trainer_id)
    assert row is not None
    assert row["name"] == "Сертификат 100 BYN"
    assert row["description"] is None
