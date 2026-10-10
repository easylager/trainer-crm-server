"""
Format (is_online) edit policy for trainer offerings.

Policy:
- description / prices / client_notice — always editable
- adding a service — always ok
- removing a service — blocked while referenced (existing remove guard)
- flipping is_online — blocked while slots / active bookings / templates / groups
  reference that service_id; cancelled bookings alone do not lock
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    ensure_trainer_service_format_changes_allowed,
    list_trainer_service_ids_format_locked,
    update_trainer_profile,
)


async def _seed_owned_pair(db_session) -> tuple[int, int, int]:
    """Trainer plus two services he authored — only those may be marked online."""
    seed = (
        await db_session.execute(
            text(
                "SELECT id FROM services WHERE created_by_trainer_id IS NULL ORDER BY id LIMIT 1"
            )
        )
    ).scalar()
    if seed is None:
        pytest.skip("need a platform service")
    tid = await create_trainer(
        db_session,
        profile={"first_name": "Fmt", "last_name": "Lock", "age": 31},
        service_ids=[int(seed)],
        arena_ids=[],
    )
    inserted: list[int] = []
    for label in ("A", "B"):
        sid = (
            await db_session.execute(
                text(
                    """
                    INSERT INTO services (name, sort_order, is_public, created_by_trainer_id)
                    VALUES (:name, 100, false, :tid)
                    RETURNING id
                    """
                ),
                {"name": f"Своя {label} {tid}", "tid": tid},
            )
        ).scalar_one()
        inserted.append(int(sid))
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_services (trainer_id, service_id, is_online)
            VALUES (:tid, :s1, false), (:tid, :s2, false)
            """
        ),
        {"tid": tid, "s1": inserted[0], "s2": inserted[1]},
    )
    await db_session.commit()
    return tid, inserted[0], inserted[1]


@pytest.mark.asyncio
async def test_can_flip_format_when_service_unused(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)

    assert await list_trainer_service_ids_format_locked(db_session, tid) == []
    await ensure_trainer_service_format_changes_allowed(db_session, tid, {s1: True})
    ok = await update_trainer_profile(
        db_session,
        tid,
        profile={},
        services=[
            {"service_id": s1, "is_online": True, "price_tiers": []},
            {"service_id": s2, "is_online": False, "price_tiers": []},
        ],
    )
    assert ok is True
    online = (
        await db_session.execute(
            text(
                "SELECT COALESCE(is_online, false) FROM trainer_services "
                "WHERE trainer_id = :tid AND service_id = :sid"
            ),
            {"tid": tid, "sid": s1},
        )
    ).scalar()
    assert online is True


@pytest.mark.asyncio
async def test_cannot_flip_format_when_slot_references_service(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, '10:00:00', '11:00:00', 'available', 1, :sid)
            """
        ),
        {"tid": tid, "d": date(2030, 6, 1), "sid": s1},
    )
    await db_session.commit()

    locked = await list_trainer_service_ids_format_locked(db_session, tid)
    assert s1 in locked
    assert s2 not in locked

    with pytest.raises(ValueError, match="формат"):
        await ensure_trainer_service_format_changes_allowed(db_session, tid, {s1: True})

    with pytest.raises(ValueError, match="формат"):
        await update_trainer_profile(
            db_session,
            tid,
            profile={},
            services=[
                {"service_id": s1, "is_online": True, "price_tiers": []},
                {"service_id": s2, "is_online": False, "price_tiers": []},
            ],
        )


@pytest.mark.asyncio
async def test_cannot_flip_format_when_active_booking(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)

    slot_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
                VALUES (:tid, :d, '14:00:00', '15:00:00', 'booked', 1)
                RETURNING id
                """
            ),
            {"tid": tid, "d": date(2030, 6, 10)},
        )
    ).scalar_one()
    client_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
                VALUES (:tg, 'Client', 'Fmt', '+375291110001', '375291110001')
                RETURNING id
                """
            ),
            {"tg": 9_100_000_000 + (tid % 1_000_000)},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:slot, :tid, :cid, :sid, 'confirmed')
            """
        ),
        {"slot": slot_id, "tid": tid, "cid": client_id, "sid": s1},
    )
    await db_session.commit()

    assert s1 in await list_trainer_service_ids_format_locked(db_session, tid)
    with pytest.raises(ValueError, match="формат"):
        await update_trainer_profile(
            db_session,
            tid,
            profile={},
            services=[
                {"service_id": s1, "is_online": True, "price_tiers": []},
                {"service_id": s2, "is_online": False, "price_tiers": []},
            ],
        )


@pytest.mark.asyncio
async def test_cancelled_booking_does_not_lock_format(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)

    slot_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
                VALUES (:tid, :d, '16:00:00', '17:00:00', 'cancelled', 1)
                RETURNING id
                """
            ),
            {"tid": tid, "d": date(2030, 6, 12)},
        )
    ).scalar_one()
    client_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
                VALUES (:tg, 'Gone', 'Fmt', '+375291110002', '375291110002')
                RETURNING id
                """
            ),
            {"tg": 9_200_000_000 + (tid % 1_000_000)},
        )
    ).scalar_one()
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status)
            VALUES (:slot, :tid, :cid, :sid, 'cancelled')
            """
        ),
        {"slot": slot_id, "tid": tid, "cid": client_id, "sid": s1},
    )
    await db_session.commit()

    assert s1 not in await list_trainer_service_ids_format_locked(db_session, tid)
    await update_trainer_profile(
        db_session,
        tid,
        profile={},
        services=[
            {"service_id": s1, "is_online": True, "price_tiers": []},
            {"service_id": s2, "is_online": False, "price_tiers": []},
        ],
    )
    online = (
        await db_session.execute(
            text(
                "SELECT COALESCE(is_online, false) FROM trainer_services "
                "WHERE trainer_id = :tid AND service_id = :sid"
            ),
            {"tid": tid, "sid": s1},
        )
    ).scalar()
    assert online is True


@pytest.mark.asyncio
async def test_can_edit_price_and_description_while_format_locked(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, '11:00:00', '12:00:00', 'available', 1, :sid)
            """
        ),
        {"tid": tid, "d": date(2030, 7, 1), "sid": s1},
    )
    await db_session.commit()

    ok = await update_trainer_profile(
        db_session,
        tid,
        profile={},
        services=[
            {
                "service_id": s1,
                "is_online": False,
                "description": "Обновлённое описание",
                "price_tiers": [{"tier_kind": "adult", "price_byn": 55}],
            },
            {"service_id": s2, "is_online": False, "price_tiers": []},
        ],
    )
    assert ok is True
    row = (
        await db_session.execute(
            text(
                """
                SELECT description, COALESCE(is_online, false), price_cents
                FROM trainer_services
                WHERE trainer_id = :tid AND service_id = :sid
                """
            ),
            {"tid": tid, "sid": s1},
        )
    ).fetchone()
    assert row is not None
    assert row[0] == "Обновлённое описание"
    assert row[1] is False
    assert int(row[2]) == 5500


@pytest.mark.asyncio
async def test_legacy_service_ids_update_preserves_is_online(db_session) -> None:
    """service_ids-only PATCH must not wipe online flags (short tuple defaulted to false)."""
    tid, s1, s2 = await _seed_owned_pair(db_session)
    await db_session.execute(
        text(
            "UPDATE trainer_services SET is_online = true "
            "WHERE trainer_id = :tid AND service_id = :sid"
        ),
        {"tid": tid, "sid": s1},
    )
    await db_session.commit()

    await update_trainer_profile(db_session, tid, profile={}, service_ids=[s1, s2])
    online = (
        await db_session.execute(
            text(
                "SELECT COALESCE(is_online, false) FROM trainer_services "
                "WHERE trainer_id = :tid AND service_id = :sid"
            ),
            {"tid": tid, "sid": s1},
        )
    ).scalar()
    assert online is True


@pytest.mark.asyncio
async def test_same_format_noop_allowed_when_locked(db_session) -> None:
    tid, s1, s2 = await _seed_owned_pair(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, service_id)
            VALUES (:tid, :d, '09:00:00', '10:00:00', 'available', 1, :sid)
            """
        ),
        {"tid": tid, "d": date(2030, 8, 1), "sid": s1},
    )
    await db_session.commit()

    # Same is_online=false — not a flip.
    await ensure_trainer_service_format_changes_allowed(db_session, tid, {s1: False})
