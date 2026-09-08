"""
EPIC1: client_profile_links — one Telegram account acting as several client profiles.

See docs/adr/004-multi-profile-clients.md / docs/epics/client-multi-profile.md.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_profile_use_cases import (
    MAX_GUARDIAN_PROFILES_PER_ACCOUNT,
    _ensure_self_link,
    create_guardian_profile,
    list_accessible_profiles,
    resolve_acting_client_id,
    set_default_profile,
)


async def _insert_client(
    db_session: AsyncSession,
    *,
    telegram_id: int | None = None,
    first_name: str = "Client",
    last_name: str | None = None,
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name, telegram_id, is_sandbox)
            VALUES (:fn, :ln, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "ln": last_name, "tid": telegram_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_resolve_without_profile_matches_legacy_and_backfills_self_link(
    db_session: AsyncSession,
) -> None:
    """A client that predates Slice 1 (no client_profile_links row yet) still resolves,
    and the self link is lazily created — this is the backward-compat guarantee the
    whole migration rests on."""
    telegram_id = 900001
    client_id = await _insert_client(db_session, telegram_id=telegram_id, first_name="Иван")
    await db_session.commit()

    resolved = await resolve_acting_client_id(db_session, telegram_id)
    await db_session.commit()

    assert resolved == client_id
    row = (
        await db_session.execute(
            text(
                """
                SELECT role, is_default FROM client_profile_links
                WHERE account_telegram_id = :tid AND profile_client_id = :cid
                """
            ),
            {"tid": telegram_id, "cid": client_id},
        )
    ).one()
    assert row[0] == "self"
    assert row[1] is True


@pytest.mark.asyncio
async def test_resolve_ignores_unauthorized_requested_profile(db_session: AsyncSession) -> None:
    """A profile id the account has no link to must never leak — silently falls back
    to the account's own row rather than raising or granting access."""
    owner_tid = 900002
    owner_cid = await _insert_client(db_session, telegram_id=owner_tid, first_name="Owner")
    stranger_cid = await _insert_client(db_session, telegram_id=900003, first_name="Stranger")
    await db_session.commit()

    resolved = await resolve_acting_client_id(db_session, owner_tid, requested_profile_id=stranger_cid)
    await db_session.commit()

    assert resolved == owner_cid


@pytest.mark.asyncio
async def test_create_guardian_profile_and_resolve_by_id(db_session: AsyncSession) -> None:
    parent_tid = 900004
    await _insert_client(db_session, telegram_id=parent_tid, first_name="Parent")
    await db_session.commit()

    child_id = await create_guardian_profile(
        db_session, parent_tid, first_name="Ваня", last_name="Иванов"
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT telegram_id, first_name, last_name FROM clients WHERE id = :cid"),
            {"cid": child_id},
        )
    ).one()
    assert row[0] is None  # no Telegram identity of its own
    assert row[1] == "Ваня"
    assert row[2] == "Иванов"

    resolved = await resolve_acting_client_id(db_session, parent_tid, requested_profile_id=child_id)
    assert resolved == child_id


@pytest.mark.asyncio
async def test_two_children_have_independent_history(db_session: AsyncSession) -> None:
    """The scenario from the bug report: a parent adds a second child. Both profiles
    must resolve to different client_id values, so bookings never collide."""
    parent_tid = 900005
    await _insert_client(db_session, telegram_id=parent_tid, first_name="Родитель")
    await db_session.commit()

    child1 = await create_guardian_profile(db_session, parent_tid, first_name="Аня")
    child2 = await create_guardian_profile(db_session, parent_tid, first_name="Ваня")
    await db_session.commit()

    assert child1 != child2
    assert await resolve_acting_client_id(db_session, parent_tid, requested_profile_id=child1) == child1
    assert await resolve_acting_client_id(db_session, parent_tid, requested_profile_id=child2) == child2


@pytest.mark.asyncio
async def test_list_accessible_profiles_orders_self_first_then_guardians(
    db_session: AsyncSession,
) -> None:
    parent_tid = 900006
    parent_cid = await _insert_client(db_session, telegram_id=parent_tid, first_name="Мама")
    await db_session.commit()
    child_id = await create_guardian_profile(db_session, parent_tid, first_name="Дочь")
    await db_session.commit()

    profiles = await list_accessible_profiles(db_session, parent_tid)

    assert [p["client_id"] for p in profiles] == [parent_cid, child_id]
    assert profiles[0]["role"] == "self"
    assert profiles[0]["is_default"] is True
    assert profiles[1]["role"] == "guardian"
    assert profiles[1]["is_default"] is False


@pytest.mark.asyncio
async def test_set_default_profile_switches_flag_and_rejects_foreign_profile(
    db_session: AsyncSession,
) -> None:
    parent_tid = 900007
    await _insert_client(db_session, telegram_id=parent_tid, first_name="Папа")
    await db_session.commit()
    child_id = await create_guardian_profile(db_session, parent_tid, first_name="Сын")
    await db_session.commit()

    ok = await set_default_profile(db_session, parent_tid, child_id)
    await db_session.commit()
    assert ok is True

    profiles = {p["client_id"]: p for p in await list_accessible_profiles(db_session, parent_tid)}
    assert profiles[child_id]["is_default"] is True

    foreign_cid = await _insert_client(db_session, telegram_id=900008, first_name="Чужой")
    await db_session.commit()
    rejected = await set_default_profile(db_session, parent_tid, foreign_cid)
    assert rejected is False


@pytest.mark.asyncio
async def test_guardian_profile_limit_enforced(db_session: AsyncSession) -> None:
    parent_tid = 900009
    await _insert_client(db_session, telegram_id=parent_tid, first_name="Многодетный")
    await db_session.commit()

    for i in range(MAX_GUARDIAN_PROFILES_PER_ACCOUNT):
        await create_guardian_profile(db_session, parent_tid, first_name=f"Ребёнок{i}")
    await db_session.commit()

    with pytest.raises(ValueError):
        await create_guardian_profile(db_session, parent_tid, first_name="ЛишнийРебёнок")


@pytest.mark.asyncio
async def test_family_access_member_still_resolves_via_legacy_path(
    db_session: AsyncSession,
) -> None:
    """client_family_access_members is untouched by this epic: a second parent's telegram
    must keep resolving to the shared child row exactly as before, with no explicit link row."""
    owner_tid = 900010
    owner_cid = await _insert_client(db_session, telegram_id=owner_tid, first_name="Ребёнок")
    second_parent_tid = 900011
    await db_session.execute(
        text(
            """
            INSERT INTO client_family_access_members (primary_client_id, member_telegram_id)
            VALUES (:pid, :mtid)
            """
        ),
        {"pid": owner_cid, "mtid": second_parent_tid},
    )
    await db_session.commit()

    resolved = await resolve_acting_client_id(db_session, second_parent_tid)
    assert resolved == owner_cid

    profiles = await list_accessible_profiles(db_session, second_parent_tid)
    assert any(p["client_id"] == owner_cid and p["role"] == "family_access" for p in profiles)


@pytest.mark.asyncio
async def test_ensure_self_link_never_creates_a_second_default_after_switch(
    db_session: AsyncSession,
) -> None:
    """
    Regression: a legacy clients row (raw INSERT, no self link yet — the pre-Slice-1 shape)
    gets a guardian profile added and switched to default *before* anything ever calls
    resolve/list for the account. The self link is then created for the first time here,
    lazily. It must NOT resurrect itself as a second ``is_default=true`` row — that used to
    make the switcher silently show the parent's own profile as "current" right after the
    user had just switched to their child.
    """
    parent_tid = 900012
    parent_cid = await _insert_client(db_session, telegram_id=parent_tid, first_name="Папа")
    await db_session.commit()

    child_id = await create_guardian_profile(db_session, parent_tid, first_name="Сын")
    await db_session.commit()
    assert await set_default_profile(db_session, parent_tid, child_id) is True
    await db_session.commit()

    # First-ever self-link creation for this account, happening *after* the switch.
    await _ensure_self_link(db_session, parent_tid, parent_cid)
    await db_session.commit()

    profiles = {p["client_id"]: p for p in await list_accessible_profiles(db_session, parent_tid)}
    assert profiles[child_id]["is_default"] is True
    assert profiles[parent_cid]["is_default"] is False
    assert sum(1 for p in profiles.values() if p["is_default"]) == 1


@pytest.mark.asyncio
async def test_db_rejects_two_default_rows_for_same_account(db_session: AsyncSession) -> None:
    """The invariant is also enforced at the DB level (partial unique index), independent
    of application logic — a future bug in Python code cannot silently corrupt this."""
    parent_tid = 900013
    parent_cid = await _insert_client(db_session, telegram_id=parent_tid, first_name="Мама")
    other_cid = await _insert_client(db_session, telegram_id=900014, first_name="Другой")
    await db_session.execute(
        text(
            """
            INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
            VALUES (:tid, :cid, 'self', true)
            """
        ),
        {"tid": parent_tid, "cid": parent_cid},
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
                VALUES (:tid, :cid, 'guardian', true)
                """
            ),
            {"tid": parent_tid, "cid": other_cid},
        )
    await db_session.rollback()
