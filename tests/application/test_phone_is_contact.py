"""A family phone belongs to several people: it is a contact, never an identity (TASK-314)."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import link_trainer_client_roster
from src.application.client_profile_use_cases import (
    link_guardian_profile,
    list_accessible_profiles,
    sql_client_notify_phone,
)
from src.application.client_use_cases import get_or_create_client, get_or_create_client_by_phone
from src.application.trainer_client_matches import list_client_matches, resolve_client_match
from src.application.trainer_hub_action_inbox import build_trainer_hub_action_inbox

MOM = "+375 29 111-22-33"


async def _trainer(s: AsyncSession) -> int:
    r = await s.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    return int(r.scalar_one())


async def _name(s: AsyncSession, cid: int) -> str:
    return (await s.execute(text("SELECT first_name FROM clients WHERE id = :c"), {"c": cid})).scalar_one()


async def _exists(s: AsyncSession, cid: int) -> bool:
    return (await s.execute(text("SELECT 1 FROM clients WHERE id = :c"), {"c": cid})).first() is not None


async def _add(s: AsyncSession, trainer_id: int, first_name: str, phone: str = MOM) -> int:
    cid = await get_or_create_client_by_phone(s, phone, first_name=first_name, trainer_id=trainer_id)
    await link_trainer_client_roster(s, trainer_id, cid)
    return cid


@pytest.mark.asyncio
async def test_two_siblings_with_moms_phone_are_two_students(db_session: AsyncSession) -> None:
    t = await _trainer(db_session)
    anna = await _add(db_session, t, "Анна")
    lev = await _add(db_session, t, "Лев")
    assert anna != lev
    assert await _name(db_session, anna) == "Анна"
    assert await _name(db_session, lev) == "Лев"


@pytest.mark.asyncio
async def test_same_name_same_phone_is_the_same_student(db_session: AsyncSession) -> None:
    t = await _trainer(db_session)
    first = await _add(db_session, t, "Анна")
    again = await _add(db_session, t, " анна ")
    assert again == first


@pytest.mark.asyncio
async def test_other_trainers_client_is_never_reused_or_renamed(db_session: AsyncSession) -> None:
    a, b = await _trainer(db_session), await _trainer(db_session)
    theirs = await _add(db_session, a, "Анна")
    mine = await _add(db_session, b, "Аня")
    assert mine != theirs
    assert await _name(db_session, theirs) == "Анна"


@pytest.mark.asyncio
async def test_second_parent_books_with_the_family_number(db_session: AsyncSession) -> None:
    mom = await get_or_create_client(db_session, 830001, phone=MOM, first_name="Ольга")
    dad = await get_or_create_client(db_session, 830002, phone=MOM, first_name="Игорь")
    assert mom != dad


@pytest.mark.asyncio
async def test_typed_phone_does_not_take_over_a_trainers_student(db_session: AsyncSession) -> None:
    t = await _trainer(db_session)
    anna = await _add(db_session, t, "Анна")
    mom = await get_or_create_client(db_session, 830003, phone=MOM, first_name="Ольга")
    assert mom != anna
    tid = (await db_session.execute(text("SELECT telegram_id FROM clients WHERE id = :c"), {"c": anna})).scalar()
    assert tid is None


async def _pair(s: AsyncSession) -> tuple[int, int, int]:
    t = await _trainer(s)
    anna = await _add(s, t, "Анна")
    mom = await get_or_create_client(s, 830010 + t, phone=MOM, first_name="Ольга")
    await link_trainer_client_roster(s, t, mom)
    return t, mom, anna


@pytest.mark.asyncio
async def test_match_is_offered_in_the_trainers_inbox(db_session: AsyncSession) -> None:
    t, mom, anna = await _pair(db_session)
    matches = await list_client_matches(db_session, t)
    assert [(m["client_id"], m["other_client_id"]) for m in matches] == [(mom, anna)]
    inbox = build_trainer_hub_action_inbox(onboarding={}, client_matches=matches)
    item = next(i for i in inbox["items"] if i["id"] == "client_match")
    assert item["title"] == "Похоже, Ольга — это Анна из вашего списка"


@pytest.mark.asyncio
async def test_same_person_merges_into_the_account(db_session: AsyncSession) -> None:
    t, mom, anna = await _pair(db_session)
    await resolve_client_match(db_session, t, mom, anna, "same")
    assert not await _exists(db_session, anna)
    assert await list_client_matches(db_session, t) == []


@pytest.mark.asyncio
async def test_parent_gets_the_student_as_a_profile(db_session: AsyncSession) -> None:
    t, mom, anna = await _pair(db_session)
    await resolve_client_match(db_session, t, mom, anna, "parent")
    profiles = await list_accessible_profiles(db_session, 830010 + t)
    assert {p["client_id"] for p in profiles} == {mom, anna}
    assert await list_client_matches(db_session, t) == []


@pytest.mark.asyncio
async def test_different_people_are_not_offered_again(db_session: AsyncSession) -> None:
    t, mom, anna = await _pair(db_session)
    await resolve_client_match(db_session, t, mom, anna, "different")
    assert await list_client_matches(db_session, t) == []
    assert await _exists(db_session, anna)
    with pytest.raises(LookupError):
        await resolve_client_match(db_session, t, mom, anna, "same")


@pytest.mark.asyncio
async def test_foreign_trainer_cannot_resolve_a_pair(db_session: AsyncSession) -> None:
    t, mom, anna = await _pair(db_session)
    stranger = await _trainer(db_session)
    with pytest.raises(LookupError):
        await resolve_client_match(db_session, stranger, mom, anna, "same")


@pytest.mark.asyncio
async def test_child_contact_is_the_parents_current_phone(db_session: AsyncSession) -> None:
    t = await _trainer(db_session)
    lev = await _add(db_session, t, "Лев")
    mom = await get_or_create_client(db_session, 830020, phone=MOM, first_name="Ольга")
    assert await link_guardian_profile(db_session, 830020, lev)
    await db_session.execute(
        text("UPDATE clients SET phone = '+375 33 999-88-77', phone_normalized = '375339998877' WHERE id = :c"),
        {"c": mom},
    )
    phone = (
        await db_session.execute(
            text(f"SELECT {sql_client_notify_phone('c')} FROM clients c WHERE c.id = :c"), {"c": lev}
        )
    ).scalar()
    assert phone == "+375 33 999-88-77"
