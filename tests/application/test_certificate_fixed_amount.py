"""Certificate products always carry a fixed positive amount (TASK-142/AC-001, AC-005).

"Any amount" (amount_cents IS NULL) used to let issue_certificate silently store
amount_cents=0, which the redeem query (amount_remaining_cents > 0) can never match —
an unredeemable certificate. Covered here: creation/update reject it outright, and
issue_certificate refuses to issue against a product that somehow still has it (e.g. a
pre-migration row).
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import (
    create_certificate_product,
    issue_certificate,
    update_certificate_product,
)


async def _trainer_id(db_session: AsyncSession) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_create_certificate_product_rejects_null_amount(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    with pytest.raises(ValueError):
        await create_certificate_product(
            db_session, trainer_id, name="Подарок", amount_cents=None
        )


@pytest.mark.asyncio
async def test_create_certificate_product_rejects_non_positive_amount(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    with pytest.raises(ValueError):
        await create_certificate_product(
            db_session, trainer_id, name="Подарок", amount_cents=0
        )


@pytest.mark.asyncio
async def test_update_certificate_product_rejects_null_amount(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    with pytest.raises(ValueError):
        await update_certificate_product(
            db_session, product_id, trainer_id, amount_cents=None
        )


@pytest.mark.asyncio
async def test_issue_certificate_refuses_null_amount_product(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    # Simulate a pre-migration "any amount" row directly — create_certificate_product
    # itself can no longer produce one.
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainer_certificate_products
                (trainer_id, name, amount_cents, is_active)
            VALUES (:tid, 'Legacy any-amount', NULL, true)
            RETURNING id
            """
        ),
        {"tid": trainer_id},
    )
    product_id = int(r.scalar_one())
    await db_session.commit()

    with pytest.raises(ValueError):
        await issue_certificate(
            db_session,
            trainer_id,
            product_id,
            recipient_name="Тест",
        )
