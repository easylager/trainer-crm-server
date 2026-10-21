"""Online vs venue is XOR per trainer_services.is_online offering."""

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.booking_use_cases import (
    BOOKING_ARENA_UNSPECIFIED_LABEL,
    BOOKING_ONLINE_PLACE_LABEL,
    ServiceOnlineFormatMismatch,
    confirm_booking,
    create_booking,
    create_trainer_quick_booking,
    fetch_trainer_booked_notification_payload,
    get_trainer_booking_detail_payload,
)
from src.bot import messages as bot_msg
from src.application.trainer_custom_service_use_cases import add_trainer_custom_service
from src.application.trainer_schedule_use_cases import (
    list_slots,
    replace_slots_for_day,
    trainer_offers_online_sessions,
)
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
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, capacity, status, arena_id, is_online)
            VALUES (:tid, :d, :st, :et, 1, 'available', NULL, true)
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


@pytest.mark.asyncio
async def test_no_arena_mixed_services_slot_defaults_in_person(db_session):
    """No rink + offline and online services: a new slot is очно, not online.

    The client can book the in-person service. The online service needs an explicit online slot.
    """
    sid, cid = await _seed_city_and_service(db_session)
    phone, _pn = belarus_test_phone(unique_test_telegram_id())
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Смесь", "last_name": "Форматов", "phone": phone, "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    online_sid = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO services (name, sort_order, is_public, created_by_trainer_id)
                    VALUES ('Вовов онлайн', 81, false, :tid)
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
    await sync_trainer_online_enabled_from_services(db_session, trainer_id)
    await db_session.commit()

    day = date.today() + timedelta(days=3)
    await replace_slots_for_day(db_session, trainer_id, day, {10 * 60}, 60)
    rows = await list_slots(db_session, trainer_id, day, day)
    assert len(rows) == 1
    assert rows[0]["arena_id"] is None
    assert rows[0]["is_online"] is False
    slot_id = int(rows[0]["id"])
    client_id = await _insert_client(db_session)

    with pytest.raises(ServiceOnlineFormatMismatch) as exc:
        await create_booking(
            db_session,
            slot_id,
            trainer_id,
            client_id,
            service_id=online_sid,
            created_by_trainer=False,
            arena_id=None,
        )
    assert exc.value.code == "venue_slot_needs_offline_service"

    booking_id, _ = await create_booking(
        db_session,
        slot_id,
        trainer_id,
        client_id,
        service_id=int(sid),
        created_by_trainer=False,
        arena_id=None,
    )
    assert booking_id is not None

    online_day = day + timedelta(days=1)
    await replace_slots_for_day(
        db_session, trainer_id, online_day, {11 * 60}, 60, force_null_arena=True
    )
    online_rows = await list_slots(db_session, trainer_id, online_day, online_day)
    assert len(online_rows) == 1
    assert online_rows[0]["is_online"] is True
    with pytest.raises(ServiceOnlineFormatMismatch) as online_exc:
        await create_booking(
            db_session,
            int(online_rows[0]["id"]),
            trainer_id,
            client_id,
            service_id=int(sid),
            created_by_trainer=False,
            arena_id=None,
        )
    assert online_exc.value.code == "online_slot_needs_online_service"


@pytest.mark.asyncio
async def test_confirm_online_booking_does_not_inherit_rink_added_later(db_session, monkeypatch):
    """Pending online request stays venue-less after the trainer links a rink.

    Confirm used to fill COALESCE(primary, any arena) into «Место» and the map button.
    """
    sid, cid = await _seed_city_and_service(db_session)
    monkeypatch.setattr(
        "src.application.admin_custom_service_notify.notify_admins_new_custom_service",
        _noop_notify,
    )
    phone, _pn = belarus_test_phone(unique_test_telegram_id())
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "Максим", "last_name": "Тест", "phone": phone, "city_id": cid},
        service_ids=[sid],
        arena_ids=[],
    )
    custom = await add_trainer_custom_service(db_session, trainer_id, "Вовов", is_online=True)
    online_sid = int(custom["service_id"])
    day = date.today() + timedelta(days=4)
    await replace_slots_for_day(
        db_session, trainer_id, day, {16 * 60 + 15}, 45, force_null_arena=True
    )
    slot_id = int((await list_slots(db_session, trainer_id, day, day))[0]["id"])
    client_id = await _insert_client(db_session)
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
    arena_id = int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO arenas (city_id, name, address, is_active)
                    VALUES (:cid, 'Конькобежный стадион', 'проспект Победителей, 111', true)
                    RETURNING id
                    """
                ),
                {"cid": cid},
            )
        ).scalar_one()
    )
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:tid, :aid)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await db_session.commit()

    info = await confirm_booking(db_session, int(booking_id), trainer_id)
    assert info is not None
    assert info["arena_name"] == BOOKING_ONLINE_PLACE_LABEL
    assert not (info.get("arena_address") or "").strip()
    assert info.get("map_link") is None
    text_client = bot_msg.format_client_booking_confirmed_by_trainer_text(
        date="21.10",
        day="Ср",
        time="16:15",
        trainer_name="Максим",
        service_name=info.get("service_name"),
        booking_price_cents=info.get("booking_price_cents"),
        price_tier_label=info.get("price_tier_label"),
        arena_name=info.get("arena_name"),
        arena_address=info.get("arena_address"),
    )
    assert "Онлайн" in text_client
    assert "Конькобежный" not in text_client
    assert "Победителей" not in text_client
    keyboard = bot_msg.build_client_booking_confirmed_inline_keyboard(
        map_url=info.get("map_link"),
        trainer_telegram_id=None,
    )
    assert keyboard is None
