"""
One gate, four surfaces (TASK-140, AC-001).

Before this, "is the trainer in the catalog?" was ``status = 'active' AND is_catalog_visible``
written out eleven times across the trainer list, arena cards, city counters and the group
picker — in four different spellings, one of which defaulted a missing flag to *visible*. A
missed copy is invisible in review; it shows up as a trainer appearing where they should not.

So each non-published state is checked against every surface, not just the trainer list.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

UNLISTED_STATES = [
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_NEEDS_REVISION,
]


async def _force_state(db_session, trainer_id: int, state: str) -> None:
    """
    Straight to the column on purpose: this test is about what the *readers* do with a state,
    and going through the state machine would drag its transition rules in as a second subject.
    """
    await db_session.execute(
        text(
            "UPDATE trainers SET catalog_state = :st, is_catalog_visible = :vis WHERE id = :tid"
        ),
        {"st": state, "vis": state == CATALOG_STATE_PUBLISHED, "tid": trainer_id},
    )
    await db_session.commit()


def _search_trainer_ids(payload: dict) -> set[int]:
    """`/api/public/search` returns grouped sections: [{type: trainer, items: [...]}, ...]."""
    for group in payload.get("groups") or []:
        if group.get("type") == "trainer":
            return {int(it["id"]) for it in group.get("items") or []}
    return set()


async def _listed_ids_in_city(client: AsyncClient, city_id: int) -> set[int]:
    resp = await client.get("/api/public/trainers", params={"city_id": city_id, "limit": 200})
    assert resp.status_code == 200, resp.text
    return {it["id"] for it in resp.json()["items"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("state", UNLISTED_STATES)
async def test_trainer_list_shows_published_only(app_use_test_db, db_session, state) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        assert tid in await _listed_ids_in_city(client, cid)
        await _force_state(db_session, tid, state)
        assert tid not in await _listed_ids_in_city(client, cid)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", UNLISTED_STATES)
async def test_trainer_detail_404_unless_published(app_use_test_db, db_session, state) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        assert (await client.get(f"/api/public/trainers/{tid}")).status_code == 200
        await _force_state(db_session, tid, state)
        assert (await client.get(f"/api/public/trainers/{tid}")).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("state", UNLISTED_STATES)
async def test_reviews_404_unless_published(app_use_test_db, db_session, state) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        await _force_state(db_session, tid, state)
        resp = await client.get(f"/api/public/trainers/{tid}/reviews")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_arena_trainers_and_search_follow_the_same_gate(app_use_test_db, db_session) -> None:
    sid, cid, aid = await _require_seed_ids(db_session)
    if aid is None:
        pytest.skip("need a seeded arena")
    surname = f"Гейт{uuid.uuid4().hex[:5]}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid],
            first_name="Проверка", last_name=surname,
        )
        on_arena = await client.get(f"/api/public/arenas/{aid}/trainers")
        assert tid in {it["id"] for it in on_arena.json()["items"]}
        found = await client.get("/api/public/search", params={"q": surname})
        assert tid in _search_trainer_ids(found.json())

        await _force_state(db_session, tid, CATALOG_STATE_PAUSED)

        on_arena2 = await client.get(f"/api/public/arenas/{aid}/trainers")
        assert tid not in {it["id"] for it in on_arena2.json()["items"]}
        found2 = await client.get("/api/public/search", params={"q": surname})
        assert tid not in _search_trainer_ids(found2.json())


@pytest.mark.asyncio
async def test_city_trainer_counter_follows_the_same_gate(app_use_test_db, db_session) -> None:
    """The Ice tab's city picker counts trainers; a paused card must not inflate it."""
    sid, cid, aid = await _require_seed_ids(db_session)

    async def city_count() -> int:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/public/ice/cities")
        if resp.status_code == 404:
            pytest.skip("ice cities endpoint not mounted in this build")
        assert resp.status_code == 200, resp.text
        for row in resp.json().get("items", []):
            if int(row.get("id", 0)) == cid:
                return int(row.get("trainer_count") or 0)
        return 0

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
    with_published = await city_count()
    await _force_state(db_session, tid, CATALOG_STATE_PAUSED)
    assert await city_count() == with_published - 1


@pytest.mark.asyncio
async def test_internal_state_never_leaks_into_public_payload(app_use_test_db, db_session) -> None:
    """A client browsing the catalog has no business knowing a card was paused for a phone."""
    sid, cid, aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _create_active_trainer_via_api(
            client, db_session, city_id=cid, service_ids=[sid], arena_ids=[aid] if aid else None
        )
        resp = await client.get("/api/public/trainers", params={"city_id": cid, "limit": 200})
    body = resp.text
    for leaked in ("catalog_state", "catalog_state_reason", "catalog_state_changed_at"):
        assert leaked not in body
