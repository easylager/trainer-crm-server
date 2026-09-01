"""
Phase 4 integration: GET /r/tg/{trainer_id} redirect + Lead Mode payload + profile_view tracking.

Spec: docs/plans/lead-mode-revenue-retention.md sections "Public catalog в Lead Mode" and
"Telegram-redirect tracking". The contract this file pins:

- /api/public/trainers/{id} returns lifecycle_stage / is_lead_mode / contact_telegram_url and
  produces a `profile_view` demand row (deduped by IP+UA+day).
- /r/tg/{id} produces a `contact_click` demand row, then 302-redirects to https://t.me/{username}.
- Telegram-username validity is enforced (rogue handles never become URL targets).
- ACTIVE trainers (with subscription) also receive contact_telegram_url when @username is on file.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.infrastructure.db.models import (
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_PROFILE_VIEW,
    SUBSCRIPTION_TIER_ONLINE,
)
from tests.api.test_public_catalog_integration import _create_active_trainer_via_api
from tests.api.test_webapp_client_miniapp_integration import (
    _ensure_trainer_subscription_tier,
    _require_seed_ids,
)


async def _set_telegram_username(db_session, trainer_id: int, username: str | None) -> None:
    await db_session.execute(
        text("UPDATE trainers SET telegram_username = :u WHERE id = :tid"),
        {"u": username, "tid": trainer_id},
    )
    await db_session.commit()


async def _force_lead_mode(db_session, trainer_id: int) -> None:
    """Strip the auto-created trial so the trainer falls into LEAD_MODE.

    PATCH /api/trainers/{id}/status=active spawns a trial subscription via
    ``update_trainer_status -> create_trial_subscription``. Tests that want to assert Lead Mode
    behavior need to delete that row to simulate the post-trial state without time travel.
    """
    await db_session.execute(
        text("DELETE FROM trainer_subscriptions WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    await db_session.commit()


async def _count_demand_events(db_session, trainer_id: int, kind: str) -> int:
    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM trainer_demand_events
            WHERE trainer_id = :tid AND kind = :k
            """
        ),
        {"tid": trainer_id, "k": kind},
    )
    return int(r.scalar() or 0)


# --- /api/public/trainers/{id} payload — Lead Mode fields ---


@pytest.mark.asyncio
async def test_public_trainer_detail_returns_lifecycle_for_lead_mode(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _force_lead_mode(db_session, tid)
        await _set_telegram_username(db_session, tid, "valid_handle_123")
        resp = await client.get(f"/api/public/trainers/{tid}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lifecycle_stage"] == "lead_mode"
    assert body["is_lead_mode"] is True
    assert body["contact_telegram_url"] == f"/r/tg/{tid}"
    # Internal handle must not leak into the response.
    assert "telegram_username" not in body
    # Lead Mode trainer is unbookable by definition.
    assert body["can_book"] is False
    assert body.get("booking_reason") == "no_subscription"


@pytest.mark.asyncio
async def test_public_trainer_detail_active_trainer_exposes_contact_when_username_set(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _ensure_trainer_subscription_tier(db_session, tid, SUBSCRIPTION_TIER_ONLINE)
        await _set_telegram_username(db_session, tid, "active_trainer_42")
        resp = await client.get(f"/api/public/trainers/{tid}")
    body = resp.json()
    assert body["lifecycle_stage"] == "active"
    assert body["is_lead_mode"] is False
    assert body["can_book"] is True
    assert body["contact_telegram_url"] == f"/r/tg/{tid}"


@pytest.mark.asyncio
async def test_public_trainer_detail_lead_mode_without_username_has_null_cta(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _force_lead_mode(db_session, tid)
        await _set_telegram_username(db_session, tid, None)
        resp = await client.get(f"/api/public/trainers/{tid}")
    body = resp.json()
    assert body["is_lead_mode"] is True
    # Frontend falls back to "leave a request" when there is no Telegram handle on file.
    assert body["contact_telegram_url"] is None


@pytest.mark.asyncio
async def test_public_trainer_detail_lead_mode_with_invalid_username_rejects_cta(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _force_lead_mode(db_session, tid)
        # 4 chars — below Telegram's minimum of 5; must be rejected to avoid broken t.me links.
        await _set_telegram_username(db_session, tid, "abcd")
        resp = await client.get(f"/api/public/trainers/{tid}")
    body = resp.json()
    assert body["is_lead_mode"] is True
    assert body["contact_telegram_url"] is None


# --- profile_view demand tracking ---


@pytest.mark.asyncio
async def test_public_trainer_detail_records_profile_view(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        before = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
        resp = await client.get(
            f"/api/public/trainers/{tid}",
            headers={"User-Agent": "pytest-A"},
        )
    assert resp.status_code == 200
    after = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
    assert after == before + 1


@pytest.mark.asyncio
async def test_public_trainer_detail_view_dedup_within_same_day(
    app_use_test_db, db_session
) -> None:
    """Same client refresh storm collapses to one row (sha256(ip||ua||tid||day) unique index)."""
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        before = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
        ua = "pytest-dedup-A"
        for _ in range(3):
            resp = await client.get(
                f"/api/public/trainers/{tid}",
                headers={"User-Agent": ua},
            )
            assert resp.status_code == 200
    after = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
    # Note: ASGI test client uses a synthetic remote (or empty), but UA + tid + day still produce a
    # stable hash — three refreshes from the same UA must collapse to exactly one new row.
    assert after - before == 1


@pytest.mark.asyncio
async def test_public_trainer_detail_view_distinct_ua_yields_two_rows(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        before = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
        await client.get(f"/api/public/trainers/{tid}", headers={"User-Agent": "client-A"})
        await client.get(f"/api/public/trainers/{tid}", headers={"User-Agent": "client-B"})
    after = await _count_demand_events(db_session, tid, DEMAND_EVENT_PROFILE_VIEW)
    assert after - before == 2


# --- /r/tg/{id} redirect ---


@pytest.mark.asyncio
async def test_redirect_to_telegram_records_contact_click_and_302s(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "trainer_handle")
        before = await _count_demand_events(db_session, tid, DEMAND_EVENT_CONTACT_CLICK)
        resp = await client.get(f"/r/tg/{tid}")
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith("https://t.me/trainer_handle")
    after = await _count_demand_events(db_session, tid, DEMAND_EVENT_CONTACT_CLICK)
    assert after == before + 1


@pytest.mark.asyncio
async def test_redirect_to_telegram_404_when_trainer_missing(
    app_use_test_db, db_session
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        resp = await client.get("/r/tg/9999999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_redirect_to_telegram_404_when_no_username(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, None)
        resp = await client.get(f"/r/tg/{tid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_redirect_to_telegram_404_when_invalid_username(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        # Below 5 chars — Telegram won't resolve, so we 404 instead of building a broken URL.
        await _set_telegram_username(db_session, tid, "abc")
        resp = await client.get(f"/r/tg/{tid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_redirect_to_telegram_strips_at_prefix(
    app_use_test_db, db_session
) -> None:
    """Trainers may save their handle as '@foo'; we must accept and strip the leading '@'."""
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "@stripped_handle")
        resp = await client.get(f"/r/tg/{tid}")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://t.me/stripped_handle")


@pytest.mark.asyncio
async def test_redirect_to_telegram_explicit_source_query_passes_through(
    app_use_test_db, db_session
) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "src_test_user")
        resp = await client.get(f"/r/tg/{tid}", params={"src": "catalog"})
    assert resp.status_code == 302
    # Source is forwarded into Telegram's start parameter so the trainer knows the inbound channel.
    assert "src=catalog" in resp.headers["location"]
    # And the demand row should have source='catalog'.
    r = await db_session.execute(
        text(
            """
            SELECT source FROM trainer_demand_events
            WHERE trainer_id = :tid AND kind = :k
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"tid": tid, "k": DEMAND_EVENT_CONTACT_CLICK},
    )
    assert r.scalar() == "catalog"


@pytest.mark.asyncio
async def test_redirect_to_telegram_unknown_source_query_dropped(
    app_use_test_db, db_session
) -> None:
    """Unknown source values must not pollute the column — they fall through to None silently."""
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "src_bad_user")
        resp = await client.get(f"/r/tg/{tid}", params={"src": "evil_string"})
    assert resp.status_code == 302
    r = await db_session.execute(
        text(
            """
            SELECT source FROM trainer_demand_events
            WHERE trainer_id = :tid AND kind = :k
            ORDER BY id DESC LIMIT 1
            """
        ),
        {"tid": tid, "k": DEMAND_EVENT_CONTACT_CLICK},
    )
    assert r.scalar() is None


@pytest.mark.asyncio
async def test_redirect_to_telegram_dedup_same_day(app_use_test_db, db_session) -> None:
    sid, cid, _aid = await _require_seed_ids(db_session)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as client:
        tid = await _create_active_trainer_via_api(client, db_session, city_id=cid, service_ids=[sid])
        await _set_telegram_username(db_session, tid, "dedup_user_1")
        before = await _count_demand_events(db_session, tid, DEMAND_EVENT_CONTACT_CLICK)
        ua = "pytest-redirect-dedup"
        for _ in range(4):
            resp = await client.get(f"/r/tg/{tid}", headers={"User-Agent": ua})
            assert resp.status_code == 302
    after = await _count_demand_events(db_session, tid, DEMAND_EVENT_CONTACT_CLICK)
    assert after - before == 1
