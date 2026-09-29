"""Trainer direct-issue screen: «Имя получателя» is optional there too (TASK-142/AC-004
follow-up). The client-order form (AC-004) was fixed first; manual testing surfaced the
same blocking requirement on the trainer's own "Выдать сертификат" screen
(trainer-pass-products.html/-main.js) — issue_certificate already defaulted an empty
name to "—", only the frontend alert()/guard blocked submission.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.certificate_use_cases import create_certificate_product, issue_certificate


async def _trainer_id(db_session: AsyncSession) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_issue_certificate_defaults_empty_recipient_name_to_dash(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _trainer_id(db_session)
    product_id = await create_certificate_product(
        db_session, trainer_id, name="Подарок", amount_cents=10000
    )
    instance = await issue_certificate(
        db_session, trainer_id, product_id, recipient_name=""
    )
    assert instance["recipient_name"] == "—"
