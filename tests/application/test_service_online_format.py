"""Online vs venue is XOR per trainer_services.is_online offering."""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import ServiceOnlineFormatMismatch, create_booking
from src.application.trainer_custom_service_use_cases import add_trainer_custom_service
from src.application.trainer_schedule_use_cases import trainer_offers_online_sessions
from src.application.trainer_use_cases import create_trainer, sync_trainer_online_enabled_from_services
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_city_id, require_seed_service_id


async def _seed_city_and_service(db_session) -> tuple[int, int]:
    sid = await require_seed_service_id(db_session)
    cid = await require_seed_city_id(db_session)
    return sid, cid


async def _noop_notify(**kwargs):
    return None


async def _insert_client(db_session) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (:tg, 'C', 'L', :phone, :pn)
            RETURNING id
            """
        ),
        {"tg": tg, "phone": phone, "pn": phone_n},
    )
    (client_id,) = r.fetchone()
    await db_session.commit()
    return int(client_id)


@pytest.mark.asyncio
async def test_custom_service_persists_is_online(db_session, monkeypatch):
    sid, cid = await _seed_city_and_service(db_session)
    monkeypatch.setattr(
        "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
        _noop_notify,
    )
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Он", "last_name": "Лайн", "phone": "+375291110011", "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    result = await add_trainer_custom_service(
        db_session, trainer_id, "Онлайн-консультация", is_online=True
    )
    assert result["is_online"] is True
    row = (
        await db_session.execute(
            text(
                "SELECT COALESCE(is_online, false) FROM trainer_services "
                "WHERE trainer_id = :tid AND service_id = :sid"
            ),
            {"tid": trainer_id, "sid": result["service_id"]},
        )
    ).scalar()
    assert bool(row) is True
    assert await trainer_offers_online_sessions(db_session, trainer_id) is True


@pytest.mark.asyncio
async def test_offers_online_requires_online_service_not_legacy_flag(db_session):
    sid, cid = await _seed_city_and_service(db_session)
    trainer_id = await create_trainer(
        db_session,
        profile={
            "first_name": "Флаг",
            "last_name": "Старый",
            "phone": "+375291110012",
            "city_id": cid,
        },
        service_ids=[sid],
        arena_ids=[],
    )
    await db_session.execute(
        text("UPDATE trainer_profiles SET online_enabled = true WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()
    # Legacy profile flag alone is not enough — need an online offering.
    assert await trainer_offers_online_sessions(db_session, trainer_id) is False

    await db_session.execute(
        text(
            "UPDATE trainer_services SET is_online = true "
            "WHERE trainer_id = :tid AND service_id = :sid"
        ),
        {"tid": trainer_id, "sid": sid},
    )
    await sync_trainer_online_enabled_from_services(db_session, trainer_id)
    await db_session.commit()
    assert await trainer_offers_online_sessions(db_session, trainer_id) is True


@pytest.mark.asyncio
async def test_booking_rejects_offline_service_on_online_slot(db_session):
    sid, cid = await _seed_city_and_service(db_session)
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Слот", "last_name": "Онлайн", "phone": "+375291110013", "city_id": cid},
        services=[{"service_id": sid, "is_online": True, "price_byn": 40}],
        arena_ids=[],
    )
    # Second offline service on same trainer.
    sid2 = (
        await db_session.execute(
            text("SELECT id FROM services WHERE id <> :sid ORDER BY id LIMIT 1"),
            {"sid": sid},
        )
    ).scalar()
    if sid2 is None:
        pytest.skip("need two seed services")
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents, is_online) "
            "VALUES (:tid, :sid, 4000, false)"
        ),
        {"tid": trainer_id, "sid": int(sid2)},
    )
    day = date.today() + timedelta(days=2)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, capacity, status, arena_id)
            VALUES (:tid, :d, :st, :et, 1, 'available', NULL)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": day, "st": time(10, 0), "et": time(11, 0)},
    )
    slot_id = int(r.scalar_one())
    await db_session.commit()
    client_id = await _insert_client(db_session)

    with pytest.raises(ServiceOnlineFormatMismatch) as exc:
        await create_booking(
            db_session,
            slot_id,
            trainer_id,
            client_id,
            service_id=int(sid2),
            created_by_trainer=False,
            arena_id=None,
        )
    assert exc.value.code == "online_slot_needs_online_service"

    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=sid,
        created_by_trainer=False,
        arena_id=None,
    )
    assert booking_id is not None
    arena = (
        await db_session.execute(
            text("SELECT arena_id FROM bookings WHERE id = :id"), {"id": booking_id}
        )
    ).scalar()
    assert arena is None
