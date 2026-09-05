"""TASK-048: arena_profiles slug backfill, uniqueness, public status filter."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.application.arena_profile import backfill_arena_profiles
from src.application.catalog_use_cases import list_arenas


async def _city_id(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r.scalar()
    if cid is None:
        pytest.skip("need seed cities")
    return int(cid)


async def _insert_arena(db_session, city_id: int, name: str) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
            VALUES (:cid, :name, 'ул. Тестовая, 1', true, true)
            RETURNING id
            """
        ),
        {"cid": city_id, "name": name},
    )
    arena_id = int(r.scalar_one())
    await db_session.flush()
    return arena_id


@pytest.mark.asyncio
async def test_slug_backfill_is_idempotent(db_session) -> None:
    """AC-001: second backfill does not rewrite already issued slugs."""
    cid = await _city_id(db_session)
    suffix = uuid.uuid4().hex[:8]
    a1 = await _insert_arena(db_session, cid, f"Ледовый дворец {suffix}")
    a2 = await _insert_arena(db_session, cid, f"Ледовый дворец {suffix}-B")

    first = await backfill_arena_profiles(db_session)
    await db_session.flush()
    assert first["created"] >= 2

    rows = (
        await db_session.execute(
            text("SELECT arena_id, slug FROM arena_profiles WHERE arena_id IN (:a1, :a2) ORDER BY arena_id"),
            {"a1": a1, "a2": a2},
        )
    ).fetchall()
    slugs = {int(r[0]): r[1] for r in rows}
    assert slugs[a1]
    assert slugs[a2]
    assert slugs[a1] != slugs[a2]
    assert slugs[a1].startswith("ledovyy")

    snapshot = dict(slugs)
    second = await backfill_arena_profiles(db_session)
    await db_session.flush()
    assert second["created"] == 0
    again = (
        await db_session.execute(
            text("SELECT arena_id, slug FROM arena_profiles WHERE arena_id IN (:a1, :a2)"),
            {"a1": a1, "a2": a2},
        )
    ).fetchall()
    assert {int(r[0]): r[1] for r in again} == snapshot


@pytest.mark.asyncio
async def test_duplicate_slug_in_same_city_is_rejected(db_session) -> None:
    cid = await _city_id(db_session)
    suffix = uuid.uuid4().hex[:8]
    a1 = await _insert_arena(db_session, cid, f"Арена-уник-{suffix}-1")
    a2 = await _insert_arena(db_session, cid, f"Арена-уник-{suffix}-2")
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    slug = (
        await db_session.execute(
            text("SELECT slug FROM arena_profiles WHERE arena_id = :id"), {"id": a1}
        )
    ).scalar_one()

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE arena_profiles SET slug = :slug WHERE arena_id = :id"),
                {"slug": slug, "id": a2},
            )
            await db_session.flush()


@pytest.mark.asyncio
async def test_list_arenas_includes_row_when_district_is_null(db_session) -> None:
    """AC-002: unpublished district does not hide an otherwise public arena."""
    cid = await _city_id(db_session)
    name = f"Без района {uuid.uuid4().hex[:8]}"
    arena_id = await _insert_arena(db_session, cid, name)
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    await db_session.execute(
        text("UPDATE arena_profiles SET district = NULL WHERE arena_id = :id"),
        {"id": arena_id},
    )
    await db_session.flush()

    items = await list_arenas(db_session, cid)
    match = next((a for a in items if a["id"] == arena_id), None)
    assert match is not None
    assert match.get("district") is None


@pytest.mark.asyncio
async def test_draft_profile_hidden_from_public_list_not_from_unconfirmed_path(db_session) -> None:
    """AC-005: status!=published is absent from public list_arenas, visible when unconfirmed/admin path."""
    cid = await _city_id(db_session)
    name = f"Черновик {uuid.uuid4().hex[:8]}"
    arena_id = await _insert_arena(db_session, cid, name)
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    await db_session.execute(
        text("UPDATE arena_profiles SET status = 'draft' WHERE arena_id = :id"),
        {"id": arena_id},
    )
    await db_session.flush()

    public_items = await list_arenas(db_session, cid)
    assert arena_id not in [a["id"] for a in public_items]

    trainer_items = await list_arenas(db_session, cid, include_unconfirmed=True)
    assert arena_id in [a["id"] for a in trainer_items]
