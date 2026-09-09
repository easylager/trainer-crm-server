"""TASK-058: trainer_cities — multi-city catalog membership without wiping other-city arenas."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.application.booking_use_cases import ensure_trainer_schedule_arena_link
from src.application.trainer_use_cases import update_trainer_profile
from src.infrastructure.repositories.catalog_repository import CatalogRepository
from src.infrastructure.repositories.trainer_repository import TrainerRepository
from tests.db_catalog_helpers import require_seed_service_id

# Same statements as migration 0197 — AC-004 proves the backfill is a superset, not a shrink.
_BACKFILL_FROM_PROFILE_SQL = """
INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
SELECT trainer_id, city_id, true
FROM trainer_profiles
WHERE city_id IS NOT NULL
ON CONFLICT (trainer_id, city_id) DO UPDATE
SET is_primary = true
"""
_BACKFILL_FROM_PUBLIC_ARENAS_SQL = """
INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
SELECT DISTINCT ta.trainer_id, a.city_id, false
FROM trainer_arenas ta
JOIN arenas a ON a.id = ta.arena_id
WHERE ta.is_public = true
ON CONFLICT (trainer_id, city_id) DO NOTHING
"""


async def _two_cities_with_arenas(session) -> tuple[int, int, int, int]:
    """(city_a, arena_a, city_b, arena_b) — second city is created in-test when the seed has one."""
    r = await session.execute(
        text(
            """
            SELECT a.city_id, a.id
            FROM arenas a
            WHERE COALESCE(a.is_active, true)
            ORDER BY a.city_id, a.id
            """
        )
    )
    by_city: dict[int, int] = {}
    for cid, aid in r.fetchall():
        by_city.setdefault(int(cid), int(aid))
        if len(by_city) >= 2:
            (city_a, arena_a), (city_b, arena_b) = list(by_city.items())[:2]
            return city_a, arena_a, city_b, arena_b
    if not by_city:
        pytest.skip("Need at least one active arena")
    city_a, arena_a = next(iter(by_city.items()))
    r = await session.execute(
        text("INSERT INTO cities (name, is_active) VALUES ('TASK058 other city', true) RETURNING id")
    )
    city_b = int(r.scalar_one())
    r = await session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, is_active)
            VALUES (:cid, 'TASK058 foreign rink', true)
            RETURNING id
            """
        ),
        {"cid": city_b},
    )
    arena_b = int(r.scalar_one())
    await session.commit()
    return city_a, arena_a, city_b, arena_b


async def _second_arena_in_city(session, city_id: int, skip_id: int) -> int:
    r = await session.execute(
        text(
            """
            SELECT id FROM arenas
            WHERE city_id = :cid AND COALESCE(is_active, true) AND id <> :skip
            ORDER BY id LIMIT 1
            """
        ),
        {"cid": city_id, "skip": skip_id},
    )
    row = r.fetchone()
    if row:
        return int(row[0])
    r = await session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, is_active)
            VALUES (:cid, 'TASK058 second rink', true)
            RETURNING id
            """
        ),
        {"cid": city_id},
    )
    aid = int(r.scalar_one())
    await session.commit()
    return aid


async def _insert_catalog_trainer(
    session, *, city_id: int | None, service_id: int, first_name: str = "Multi"
) -> int:
    r = await session.execute(
        text("INSERT INTO trainers (status, is_catalog_visible) VALUES ('active', true) RETURNING id")
    )
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id)
            VALUES (:tid, :fn, 'City', 30, :cid)
            """
        ),
        {"tid": trainer_id, "fn": first_name, "cid": city_id},
    )
    await session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 4000)"
        ),
        {"tid": trainer_id, "sid": service_id},
    )
    await session.commit()
    return trainer_id


async def _link_public(session, trainer_id: int, arena_id: int) -> None:
    await session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:tid, :aid, true)"),
        {"tid": trainer_id, "aid": arena_id},
    )
    await session.commit()


async def _catalog_ids(session, *, city_id: int, service_id: int | None = None, arena_id: int | None = None) -> set[int]:
    items, _total = await TrainerRepository(session).list_active_with_details(
        limit=500,
        offset=0,
        city_id=city_id,
        service_id=service_id,
        arena_id=arena_id,
    )
    return {int(t["id"]) for t in items}


async def _profile_city_catalog_ids(session, city_id: int) -> set[int]:
    r = await session.execute(
        text(
            """
            SELECT t.id
            FROM trainers t
            JOIN trainer_profiles p ON p.trainer_id = t.id
            WHERE t.status = 'active'
              AND t.is_catalog_visible = true
              AND p.city_id = :city_id
            """
        ),
        {"city_id": city_id},
    )
    return {int(row[0]) for row in r.fetchall()}


@pytest.mark.asyncio
async def test_trainer_with_arenas_in_two_cities_is_in_both_catalogs(db_session) -> None:
    """AC-001: Minsk+Moscow trainer is in both city catalogs and on both arena lists."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await _link_public(db_session, trainer_id, arena_a)
    await _link_public(db_session, trainer_id, arena_b)
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_a, "tid": trainer_id},
    )
    await db_session.commit()

    in_a = await _catalog_ids(db_session, city_id=city_a, service_id=service_id)
    in_b = await _catalog_ids(db_session, city_id=city_b, service_id=service_id)
    assert trainer_id in in_a
    assert trainer_id in in_b

    on_arena_a = await _catalog_ids(
        db_session, city_id=city_a, service_id=service_id, arena_id=arena_a
    )
    on_arena_b = await _catalog_ids(
        db_session, city_id=city_b, service_id=service_id, arena_id=arena_b
    )
    assert trainer_id in on_arena_a
    assert trainer_id in on_arena_b


@pytest.mark.asyncio
async def test_profile_save_does_not_drop_other_city_arenas(db_session) -> None:
    """AC-002: phone-only save and same-city arena payload keep the other city's arena + primary."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await _link_public(db_session, trainer_id, arena_a)
    await _link_public(db_session, trainer_id, arena_b)
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :aid WHERE id = :tid"),
        {"aid": arena_b, "tid": trainer_id},
    )
    await db_session.commit()

    ok = await update_trainer_profile(db_session, trainer_id, profile={"phone": "+375291110058"})
    assert ok is True
    repo = TrainerRepository(db_session)
    after_phone = await repo.list_trainer_arena_ids(trainer_id)
    assert arena_a in after_phone
    assert arena_b in after_phone
    row = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :tid"), {"tid": trainer_id}
    )
    assert int(row.scalar_one()) == arena_b

    # Form only showed city A checkboxes — payload is city-A arenas only.
    ok = await update_trainer_profile(
        db_session, trainer_id, profile={"phone": "+375291110059"}, arena_ids=[arena_a]
    )
    assert ok is True
    after_partial = await repo.list_trainer_arena_ids(trainer_id)
    assert arena_a in after_partial
    assert arena_b in after_partial
    row = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :tid"), {"tid": trainer_id}
    )
    assert int(row.scalar_one()) == arena_b


@pytest.mark.asyncio
async def test_arena_trainer_count_matches_city_catalog_list(db_session) -> None:
    """AC-003: list_arenas trainer_count == catalog list length for that arena, by arena city."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await _link_public(db_session, trainer_id, arena_a)
    await _link_public(db_session, trainer_id, arena_b)
    await db_session.commit()

    catalog = CatalogRepository(db_session)
    arenas_b = await catalog.list_arenas(city_b, service_id=service_id)
    match_b = next((a for a in arenas_b if a["id"] == arena_b), None)
    assert match_b is not None
    listed_b = await _catalog_ids(
        db_session, city_id=city_b, service_id=service_id, arena_id=arena_b
    )
    assert int(match_b["trainer_count"]) == len(listed_b)
    assert trainer_id in listed_b

    arenas_a = await catalog.list_arenas(city_a, service_id=service_id)
    match_a = next((a for a in arenas_a if a["id"] == arena_a), None)
    assert match_a is not None
    listed_a = await _catalog_ids(
        db_session, city_id=city_a, service_id=service_id, arena_id=arena_a
    )
    assert int(match_a["trainer_count"]) == len(listed_a)
    assert trainer_id in listed_a


@pytest.mark.asyncio
async def test_backfill_catalog_is_superset_of_profile_city_filter(db_session) -> None:
    """AC-004: after backfill each city catalog is the old p.city_id set, or larger."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    t_a = await _insert_catalog_trainer(
        db_session, city_id=city_a, service_id=service_id, first_name="OnlyA"
    )
    t_ab = await _insert_catalog_trainer(
        db_session, city_id=city_a, service_id=service_id, first_name="Both"
    )
    await _link_public(db_session, t_a, arena_a)
    await _link_public(db_session, t_ab, arena_a)
    await _link_public(db_session, t_ab, arena_b)
    await db_session.commit()

    old_a = await _profile_city_catalog_ids(db_session, city_a)
    old_b = await _profile_city_catalog_ids(db_session, city_b)
    assert t_a in old_a and t_ab in old_a
    assert t_ab not in old_b

    await db_session.execute(
        text("DELETE FROM trainer_cities WHERE trainer_id IN (:a, :b)"),
        {"a": t_a, "b": t_ab},
    )
    await db_session.execute(text(_BACKFILL_FROM_PROFILE_SQL))
    await db_session.execute(text(_BACKFILL_FROM_PUBLIC_ARENAS_SQL))
    await db_session.commit()

    new_a = await _catalog_ids(db_session, city_id=city_a)
    new_b = await _catalog_ids(db_session, city_id=city_b)
    assert old_a <= new_a
    assert old_b <= new_b
    assert t_a in new_a and t_ab in new_a
    assert t_ab in new_b


@pytest.mark.asyncio
async def test_edge001_no_profile_city_backfills_from_arenas_only(db_session) -> None:
    """EDGE-001: no profile city + arenas → arena cities; no arenas → out of catalog. No dummy city."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    with_arenas = await _insert_catalog_trainer(
        db_session, city_id=None, service_id=service_id, first_name="NoCityArenas"
    )
    await _link_public(db_session, with_arenas, arena_b)
    homeless = await _insert_catalog_trainer(
        db_session, city_id=None, service_id=service_id, first_name="NoCityNoArenas"
    )
    await db_session.commit()

    await db_session.execute(
        text("DELETE FROM trainer_cities WHERE trainer_id IN (:a, :b)"),
        {"a": with_arenas, "b": homeless},
    )
    await db_session.execute(text(_BACKFILL_FROM_PROFILE_SQL))
    await db_session.execute(text(_BACKFILL_FROM_PUBLIC_ARENAS_SQL))
    await db_session.commit()

    in_a = await _catalog_ids(db_session, city_id=city_a)
    in_b = await _catalog_ids(db_session, city_id=city_b)
    assert with_arenas not in in_a
    assert with_arenas in in_b
    assert homeless not in in_a
    assert homeless not in in_b
    r = await db_session.execute(
        text("SELECT city_id FROM trainer_cities WHERE trainer_id = :tid"),
        {"tid": homeless},
    )
    assert r.fetchall() == []


@pytest.mark.asyncio
async def test_edge002_only_one_is_primary_per_trainer(db_session) -> None:
    """EDGE-002: partial unique index — two is_primary rows for one trainer are rejected."""
    city_a, arena_a, city_b, _arena_b = await _two_cities_with_arenas(db_session)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await _link_public(db_session, trainer_id, arena_a)
    await db_session.commit()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    """
                    INSERT INTO trainer_cities (trainer_id, city_id, is_primary)
                    VALUES (:tid, :cid, true)
                    """
                ),
                {"tid": trainer_id, "cid": city_b},
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_schedule_link_allowed_in_trainer_cities_not_only_profile_city(db_session) -> None:
    """TASK-057 widened by 058: auto-link in a second trainer_cities city, refuse a third city."""
    city_a, arena_a, city_b, arena_b = await _two_cities_with_arenas(db_session)
    arena_b2 = await _second_arena_in_city(db_session, city_b, arena_b)
    service_id = await require_seed_service_id(db_session)
    trainer_id = await _insert_catalog_trainer(db_session, city_id=city_a, service_id=service_id)
    await _link_public(db_session, trainer_id, arena_a)
    await _link_public(db_session, trainer_id, arena_b)
    await db_session.commit()

    err = await ensure_trainer_schedule_arena_link(db_session, trainer_id, arena_b2)
    assert err is None
    r = await db_session.execute(
        text(
            "SELECT is_public FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"
        ),
        {"tid": trainer_id, "aid": arena_b2},
    )
    row = r.fetchone()
    assert row is not None
    assert bool(row[0]) is False

    r = await db_session.execute(
        text("INSERT INTO cities (name, is_active) VALUES ('TASK058 third city', true) RETURNING id")
    )
    city_c = int(r.scalar_one())
    r = await db_session.execute(
        text(
            "INSERT INTO arenas (city_id, name, is_active) VALUES (:cid, 'TASK058 third rink', true) RETURNING id"
        ),
        {"cid": city_c},
    )
    arena_c = int(r.scalar_one())
    await db_session.commit()
    err = await ensure_trainer_schedule_arena_link(db_session, trainer_id, arena_c)
    assert err is not None
    r = await db_session.execute(
        text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
        {"tid": trainer_id, "aid": arena_c},
    )
    assert r.fetchone() is None
