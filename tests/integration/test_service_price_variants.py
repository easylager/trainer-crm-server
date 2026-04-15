"""Price tiers per service: booking resolution and strict client pick."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

from src.application.booking_use_cases import ServicePriceVariantRequired, create_booking
from src.infrastructure.repositories.trainer_repository import TrainerRepository


@pytest.mark.asyncio
async def test_create_booking_strict_raises_when_multiple_tiers_no_pick(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'), (:tid, :sid, 'Детский', 3000, 1, 'child')
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    tomorrow = date.today() + timedelta(days=1)
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '10:00', '11:00', 'available')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r2 = await db_session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
        """),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r2.fetchone()
    await db_session.commit()

    with pytest.raises(ServicePriceVariantRequired):
        await create_booking(
            db_session,
            slot_id=slot_id,
            trainer_id=trainer_id,
            client_id=client_id,
            service_id=service_id,
            strict_service_price_variant=True,
        )


@pytest.mark.asyncio
async def test_create_booking_with_variant_id_snapshots_price(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await db_session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) VALUES (:tid, 'T', 'T', 30)"
        ),
        {"tid": trainer_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_service_price_variants (trainer_id, service_id, label, price_cents, sort_order, tier_kind)
            VALUES (:tid, :sid, 'Взрослый', 5000, 0, 'adult'), (:tid, :sid, 'Детский', 3000, 1, 'child')
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await db_session.execute(
        text(
            """
            SELECT id FROM trainer_service_price_variants
            WHERE trainer_id = :tid AND service_id = :sid AND sort_order = 1
            """
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    (child_variant_id,) = r.fetchone()
    tomorrow = date.today() + timedelta(days=1)
    r = await db_session.execute(
        text("""
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, '11:00', '12:00', 'available')
            RETURNING id
        """),
        {"tid": trainer_id, "d": tomorrow},
    )
    (slot_id,) = r.fetchone()
    ctg = unique_test_telegram_id()
    phone, phone_normalized = belarus_test_phone(ctg)
    r2 = await db_session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'C', :phone, :pn)
            RETURNING id
        """),
        {"tg": ctg, "phone": phone, "pn": phone_normalized},
    )
    (client_id,) = r2.fetchone()
    await db_session.commit()

    bid, _ = await create_booking(
        db_session,
        slot_id=slot_id,
        trainer_id=trainer_id,
        client_id=client_id,
        service_id=service_id,
        service_price_variant_id=int(child_variant_id),
        strict_service_price_variant=True,
    )
    assert bid is not None
    r3 = await db_session.execute(
        text(
            "SELECT booking_price_cents, service_price_variant_id FROM bookings WHERE id = :id"
        ),
        {"id": bid},
    )
    bpc, vid = r3.fetchone()
    assert int(bpc) == 3000
    assert int(vid) == int(child_variant_id)


@pytest.mark.asyncio
async def test_set_trainer_services_writes_tiers_and_anchor(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    repo = TrainerRepository(db_session)
    await repo.set_trainer_services(
        trainer_id,
        [
            (
                service_id,
                [("adult", 8000), ("child", 5000)],
            )
        ],
    )
    await db_session.commit()
    r = await db_session.execute(
        text("SELECT price_cents FROM trainer_services WHERE trainer_id = :t AND service_id = :s"),
        {"t": trainer_id, "s": service_id},
    )
    assert r.scalar() == 8000
    r2 = await db_session.execute(
        text(
            """
            SELECT label, price_cents, sort_order, tier_kind FROM trainer_service_price_variants
            WHERE trainer_id = :t AND service_id = :s ORDER BY sort_order
            """
        ),
        {"t": trainer_id, "s": service_id},
    )
    rows = r2.fetchall()
    assert len(rows) == 2
    # Display order matches PRICE_TIER_ORDER (child before adult), not input tuple order.
    assert rows[0][0] == "Детский" and rows[0][1] == 5000 and rows[0][2] == 0 and rows[0][3] == "child"
    assert rows[1][0] == "Взрослый" and rows[1][1] == 8000 and rows[1][2] == 1 and rows[1][3] == "adult"


@pytest.mark.asyncio
async def test_set_trainer_services_stores_description(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    repo = TrainerRepository(db_session)
    await repo.set_trainer_services(
        trainer_id,
        [
            (
                service_id,
                [("adult", 5000)],
                "Индивидуально, 60 мин.",
            )
        ],
    )
    await db_session.commit()
    r = await db_session.execute(
        text("SELECT description FROM trainer_services WHERE trainer_id = :t AND service_id = :s"),
        {"t": trainer_id, "s": service_id},
    )
    assert (r.scalar() or "").strip() == "Индивидуально, 60 мин."
    loaded = await repo.get_by_id(trainer_id)
    assert loaded is not None
    svcs = loaded.get("services") or []
    assert len(svcs) == 1
    assert svcs[0].get("description") == "Индивидуально, 60 мин."


@pytest.mark.asyncio
async def test_set_trainer_services_stores_client_notice(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    repo = TrainerRepository(db_session)
    notice = "Коньки и билет на лёд — на кассе арены, не входят в стоимость занятия."
    await repo.set_trainer_services(
        trainer_id,
        [
            (
                service_id,
                [("adult", 5000)],
                "Индивидуально, 60 мин.",
                None,
                notice,
            )
        ],
    )
    await db_session.commit()
    r = await db_session.execute(
        text("SELECT client_notice FROM trainer_services WHERE trainer_id = :t AND service_id = :s"),
        {"t": trainer_id, "s": service_id},
    )
    assert (r.scalar() or "").strip() == notice
    loaded = await repo.get_by_id(trainer_id)
    assert loaded is not None
    svcs = loaded.get("services") or []
    assert len(svcs) == 1
    assert svcs[0].get("client_notice") == notice


@pytest.mark.asyncio
async def test_set_trainer_services_stores_group_price_override(db_session: AsyncSession) -> None:
    service_id = await require_seed_service_id(db_session)
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    repo = TrainerRepository(db_session)
    await repo.set_trainer_services(
        trainer_id,
        [
            (
                service_id,
                [("adult", 8000), ("child", 5000)],
                None,
                3500,
            )
        ],
    )
    await db_session.commit()
    r = await db_session.execute(
        text(
            "SELECT price_cents, group_price_cents FROM trainer_services WHERE trainer_id = :t AND service_id = :s"
        ),
        {"t": trainer_id, "s": service_id},
    )
    anchor, gpc = r.fetchone()
    assert int(anchor) == 8000
    assert int(gpc) == 3500
    loaded = await repo.get_by_id(trainer_id)
    assert loaded is not None
    svcs = loaded.get("services") or []
    assert len(svcs) == 1
    assert svcs[0].get("group_price_cents") == 3500
    assert svcs[0].get("group_price_byn") == 35.0
