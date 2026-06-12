"""Pass product tier scope must match trainer profile price tiers."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.pass_product_use_cases import (
    create_pass_product,
    update_pass_product,
    validate_pass_product_tier_scope,
)
from tests.db_catalog_helpers import require_seed_service_id


async def _seed_trainer_with_tiers(db_session, *, tiers: list[str]) -> tuple[int, int]:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    for i, kind in enumerate(tiers):
        await db_session.execute(
            text(
                """
                INSERT INTO trainer_service_price_variants
                    (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
                VALUES (:tid, :sid, :lab, 5000, :ord, :kind)
                """
            ),
            {"tid": trainer_id, "sid": service_id, "lab": kind, "ord": i, "kind": kind},
        )
    await db_session.commit()
    return trainer_id, service_id


@pytest.mark.asyncio
async def test_validate_pass_rejects_tier_missing_on_service(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_tiers(db_session, tiers=["adult"])
    with pytest.raises(ValueError, match="Детский"):
        await validate_pass_product_tier_scope(
            db_session, trainer_id, [service_id], ["child"]
        )


@pytest.mark.asyncio
async def test_validate_pass_accepts_tier_on_service(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_tiers(db_session, tiers=["adult"])
    await validate_pass_product_tier_scope(db_session, trainer_id, [service_id], ["adult"])


@pytest.mark.asyncio
async def test_create_pass_product_rejects_mismatched_tier(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_tiers(db_session, tiers=["adult"])
    with pytest.raises(ValueError):
        await create_pass_product(
            db_session,
            trainer_id,
            name="5 adult",
            sessions_total=5,
            price_cents=50_000,
            service_ids=[service_id],
            tier_kinds=["child"],
        )


@pytest.mark.asyncio
async def test_create_pass_product_accepts_matching_tier(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_tiers(db_session, tiers=["adult"])
    pk = await create_pass_product(
        db_session,
        trainer_id,
        name="5 adult",
        sessions_total=5,
        price_cents=50_000,
        service_ids=[service_id],
        tier_kinds=["adult"],
    )
    assert pk > 0


@pytest.mark.asyncio
async def test_update_pass_product_rejects_mismatched_tier(db_session) -> None:
    trainer_id, service_id = await _seed_trainer_with_tiers(db_session, tiers=["adult"])
    pk = await create_pass_product(
        db_session,
        trainer_id,
        name="Open",
        sessions_total=5,
        price_cents=50_000,
        service_ids=[service_id],
        tier_kinds=[],
    )
    with pytest.raises(ValueError):
        await update_pass_product(
            db_session,
            pk,
            trainer_id,
            tier_kinds=["child"],
        )
