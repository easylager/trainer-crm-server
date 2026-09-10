"""Hub «без бота» / fill-slots must use reachable Telegram (guardian links), not own telegram_id only."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    count_trainer_fill_slots_invite_candidates,
    list_trainer_clients,
    list_trainer_fill_slots_invite_candidates,
)
from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist


def _tg() -> int:
    return 9_100_000_000 + (uuid.uuid4().int % 80_000_000)


@pytest.mark.asyncio
async def test_guardian_child_counts_as_in_bot_for_hub_hints(db_session: AsyncSession) -> None:
    """
    Child row has telegram_id NULL but is linked to a parent account Telegram.
    Hub must not show «Клиенты без бота»; fill-slots must list the child as reachable.
    """
    parent_tg = _tg()
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    tid = int(r.scalar_one())
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg WHERE id = :id"),
        {"tg": _tg(), "id": tid},
    )

    r_parent = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, is_sandbox)
            VALUES (:tg, 'Parent', false)
            RETURNING id
            """
        ),
        {"tg": parent_tg},
    )
    parent_id = int(r_parent.scalar_one())
    r_child = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, is_sandbox)
            VALUES (NULL, 'Child', false)
            RETURNING id
            """
        )
    )
    child_id = int(r_child.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO client_profile_links
              (account_telegram_id, profile_client_id, role, is_default)
            VALUES
              (:tg, :parent, 'self', false),
              (:tg, :child, 'guardian', true)
            """
        ),
        {"tg": parent_tg, "parent": parent_id, "child": child_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"
        ),
        {"tid": tid, "cid": child_id},
    )
    await db_session.commit()

    checklist = await get_trainer_onboarding_checklist(db_session, tid)
    assert checklist is not None
    assert checklist.get("open_loop_clients_no_telegram_count") == 0
    assert checklist.get("fill_slots_invite_candidates_count") == 1

    fill = await list_trainer_fill_slots_invite_candidates(db_session, tid, limit=10)
    assert len(fill) == 1
    assert fill[0]["id"] == child_id
    assert fill[0].get("has_telegram") is True

    assert await count_trainer_fill_slots_invite_candidates(db_session, tid) == 1

    offline = await list_trainer_clients(db_session, tid, limit=50, in_bot=False)
    assert all(c["id"] != child_id for c in offline)
    online = await list_trainer_clients(db_session, tid, limit=50, in_bot=True)
    assert any(c["id"] == child_id for c in online)
