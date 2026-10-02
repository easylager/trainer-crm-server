"""TASK-141 (S5): collective catalog state machine — self-serve, no moderator."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from src.application.collective_catalog_state import (
    COLLECTIVE_CATALOG_ACTOR_OPERATOR,
    COLLECTIVE_CATALOG_STATE_DRAFT,
    COLLECTIVE_CATALOG_STATE_HIDDEN,
    COLLECTIVE_CATALOG_STATE_PUBLISHED,
    CollectiveCatalogStateTransitionError,
    get_collective_catalog_state,
    list_collective_catalog_events,
    set_collective_catalog_state,
)
from src.application.collective_use_cases import create_collective_draft

pytestmark = pytest.mark.collective


async def _draft_collective(db_session, slug: str) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    return int(created["id"])


@pytest.mark.asyncio
async def test_new_collective_starts_in_draft(db_session) -> None:
    cid = await _draft_collective(db_session, "cat-state-fresh")
    state = await get_collective_catalog_state(db_session, cid)
    assert state["catalog_state"] == COLLECTIVE_CATALOG_STATE_DRAFT


@pytest.mark.asyncio
async def test_draft_to_published_to_hidden_to_published(db_session) -> None:
    cid = await _draft_collective(db_session, "cat-state-cycle")

    changed = await set_collective_catalog_state(
        db_session, cid, COLLECTIVE_CATALOG_STATE_PUBLISHED, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
    )
    assert changed is True
    state = await get_collective_catalog_state(db_session, cid)
    assert state["catalog_state"] == COLLECTIVE_CATALOG_STATE_PUBLISHED

    await set_collective_catalog_state(
        db_session, cid, COLLECTIVE_CATALOG_STATE_HIDDEN, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
    )
    state = await get_collective_catalog_state(db_session, cid)
    assert state["catalog_state"] == COLLECTIVE_CATALOG_STATE_HIDDEN

    await set_collective_catalog_state(
        db_session, cid, COLLECTIVE_CATALOG_STATE_PUBLISHED, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
    )
    state = await get_collective_catalog_state(db_session, cid)
    assert state["catalog_state"] == COLLECTIVE_CATALOG_STATE_PUBLISHED

    events = await list_collective_catalog_events(db_session, cid)
    assert [e["to_state"] for e in events] == [
        COLLECTIVE_CATALOG_STATE_PUBLISHED,
        COLLECTIVE_CATALOG_STATE_HIDDEN,
        COLLECTIVE_CATALOG_STATE_PUBLISHED,
    ]


@pytest.mark.asyncio
async def test_draft_to_hidden_is_not_allowed(db_session) -> None:
    cid = await _draft_collective(db_session, "cat-state-bad-edge")
    with pytest.raises(CollectiveCatalogStateTransitionError):
        await set_collective_catalog_state(
            db_session, cid, COLLECTIVE_CATALOG_STATE_HIDDEN, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
        )


@pytest.mark.asyncio
async def test_same_state_is_a_noop(db_session) -> None:
    cid = await _draft_collective(db_session, "cat-state-noop")
    changed = await set_collective_catalog_state(
        db_session, cid, COLLECTIVE_CATALOG_STATE_DRAFT, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
    )
    assert changed is False


@pytest.mark.asyncio
async def test_missing_collective_returns_false(db_session) -> None:
    changed = await set_collective_catalog_state(
        db_session, 9_999_999, COLLECTIVE_CATALOG_STATE_PUBLISHED, actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR
    )
    assert changed is False
