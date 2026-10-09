"""Online vs venue is XOR per trainer_services.is_online offering."""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    BOOKING_ARENA_UNSPECIFIED_LABEL,
    BOOKING_ONLINE_PLACE_LABEL,
    ServiceOnlineFormatMismatch,
    create_booking,
    create_trainer_quick_booking,
    fetch_trainer_booked_notification_payload,
    get_trainer_booking_detail_payload,
)
from src.bot import messages as bot_msg
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
    assert result["allows_online"] is True
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
async def test_platform_service_cannot_be_marked_online(db_session):
    sid, cid = await _seed_city_and_service(db_session)
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "База", "last_name": "Очно", "phone": "+375291110014", "city_id": cid},
        services=[{"service_id": sid, "is_online": True, "price_byn": 40}],
        arena_ids=[],
    )
    online = (
        await db_session.execute(
            text(
                "SELECT COALESCE(is_online, false) FROM trainer_services "
                "WHERE trainer_id = :tid AND service_id = :sid"
            ),
            {"tid": trainer_id, "sid": sid},
        )
    ).scalar()
    assert bool(online) is False
    flag = (
        await db_session.execute(
            text("SELECT COALESCE(online_enabled, false) FROM trainer_profiles WHERE trainer_id = :tid"),
            {"tid": trainer_id},
        )
    ).scalar()
    assert bool(flag) is False


@pytest.mark.asyncio
async def test_naming_a_platform_service_does_not_make_it_online(db_session, monkeypatch):
    sid, cid = await _seed_city_and_service(db_session)
    monkeypatch.setattr(
        "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
        _noop_notify,
    )
    name = (
        await db_session.execute(text("SELECT name FROM services WHERE id = :sid"), {"sid": sid})
    ).scalar()
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Имя", "last_name": "Каталог", "phone": "+375291110015", "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    result = await add_trainer_custom_service(db_session, trainer_id, str(name), is_online=True)
    assert result["created"] is False
    assert result["allows_online"] is False
    assert result["is_online"] is False
    assert result["service_id"] == sid


@pytest.mark.asyncio
async def test_booking_rejects_offline_service_on_online_slot(db_session):
    sid, cid = await _seed_city_and_service(db_session)
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Слот", "last_name": "Онлайн", "phone": "+375291110013", "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    online_sid = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO services (name, sort_order, is_public, created_by_trainer_id)
                    VALUES ('Онлайн-консультация слот', 80, false, :tid)
                    RETURNING id
                    """
                ),
                {"tid": trainer_id},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents, is_online) "
            "VALUES (:tid, :sid, 4000, true)"
        ),
        {"tid": trainer_id, "sid": online_sid},
    )
    sid2 = sid
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
        service_id=online_sid,
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


@pytest.mark.asyncio
async def test_quick_book_online_service_drops_venue(db_session, monkeypatch):
    """Online offering is venue-less even when the client still sends an arena."""
    sid, cid = await _seed_city_and_service(db_session)
    monkeypatch.setattr(
        "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
        _noop_notify,
    )
    arena_a = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, is_active)
                    VALUES (:cid, 'Тестовый каток', true)
                    RETURNING id
                    """
                ),
                {"cid": cid},
            )
        ).scalar_one()
    )
    arena_b = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, is_active)
                    VALUES (:cid, 'Второй каток', true)
                    RETURNING id
                    """
                ),
                {"cid": cid},
            )
        ).scalar_one()
    )
    await db_session.commit()
    phone, _pn = belarus_test_phone(unique_test_telegram_id())
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Он", "last_name": "Лайн", "phone": phone, "city_id": cid},
        service_ids=[sid],
        arena_ids=[arena_a, arena_b],
    )
    custom = await add_trainer_custom_service(
        db_session, trainer_id, "Онлайн разбор", is_online=True
    )
    client_id = await _insert_client(db_session)
    result = await create_trainer_quick_booking(
        db_session,
        trainer_id=trainer_id,
        slot_date=date.today() + timedelta(days=4),
        start_minutes=11 * 60,
        duration_minutes=60,
        client_id=client_id,
        service_id=int(custom["service_id"]),
        arena_id=arena_a,
    )
    assert result is not None
    booking_id, slot_id, _m1, _m2 = result
    slot_arena = (
        await db_session.execute(
            text("SELECT arena_id FROM slots WHERE id = :id"), {"id": slot_id}
        )
    ).scalar()
    assert slot_arena is None
    detail = await get_trainer_booking_detail_payload(db_session, int(booking_id), trainer_id)
    assert detail is not None
    assert detail["arenas_str"] == BOOKING_ONLINE_PLACE_LABEL
    payload = await fetch_trainer_booked_notification_payload(db_session, int(booking_id))
    assert payload is not None
    assert payload["arena_name"] == BOOKING_ONLINE_PLACE_LABEL
    assert not (payload.get("arena_address") or "").strip()
    notice = bot_msg.format_client_trainer_booked_you_html(
        date="10.10",
        day="Сб",
        time="06:00",
        trainer_name="Максим",
        service_name="Онлайн разбор",
        booking_price_cents=3300,
        price_tier_label="Взрослый",
        arena_name=payload["arena_name"],
        arena_address=payload.get("arena_address"),
        duration_minutes=45,
        map_link=payload.get("map_link"),
    )
    assert "Онлайн" in notice
    assert "уточните у тренера" not in notice


@pytest.mark.asyncio
async def test_quick_book_venue_service_without_arenas_is_not_rejected(db_session):
    """No venues and no online offering: a venue-less slot still books a venue service.

    Stale trainer_profiles.online_enabled must not turn that slot into an online slot.
    """
    sid, cid = await _seed_city_and_service(db_session)
    phone, _pn = belarus_test_phone(unique_test_telegram_id())
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Без", "last_name": "Площадок", "phone": phone, "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    await db_session.execute(
        text("UPDATE trainer_profiles SET online_enabled = true WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()
    client_id = await _insert_client(db_session)
    result = await create_trainer_quick_booking(
        db_session,
        trainer_id=trainer_id,
        slot_date=date.today() + timedelta(days=5),
        start_minutes=12 * 60,
        duration_minutes=45,
        client_id=client_id,
        service_id=sid,
        arena_id=None,
    )
    assert result is not None
    booking_id, slot_id, _m1, _m2 = result
    slot_arena = (
        await db_session.execute(
            text("SELECT arena_id FROM slots WHERE id = :id"), {"id": slot_id}
        )
    ).scalar()
    assert slot_arena is None
    detail = await get_trainer_booking_detail_payload(db_session, int(booking_id), trainer_id)
    assert detail is not None
    assert detail["arenas_str"] == BOOKING_ARENA_UNSPECIFIED_LABEL
