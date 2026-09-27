"""
The «Каталог» section API (TASK-140, AC-009/011/012/014).

The screen exists to answer «в каталоге я или нет, и что с этим делать», so these tests check the
payload actually carries that answer — state, reason, both versions of a pending edit, the soft
warnings, and the history — and that each action lands in the state machine rather than writing
the column behind its back.
"""
from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_MODERATOR,
    REASON_MODERATOR_APPROVED,
    REASON_TRAINER_SUBMITTED,
    set_catalog_state,
)
from src.application.trainer_use_cases import create_trainer
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)
from tests.api.test_webapp_trainer_miniapp_profile_integration import (
    _fresh_trainer_telegram_id,
    patch_trainer_init_auth,
)
from tests.api.test_webapp_client_miniapp_integration import _require_seed_ids

HEADERS = {"X-Telegram-Init-Data": "mock"}


async def _complete_trainer(db_session, *, published: bool = False) -> tuple[int, int]:
    """A trainer whose card meets the submission bar. Returns (trainer_id, telegram_id)."""
    sid, cid, aid = await _require_seed_ids(db_session)
    if aid is None:
        pytest.skip("need a seeded arena")
    tid = await create_trainer(
        db_session,
        profile={
            "first_name": "Карточка",
            "last_name": f"Тест{uuid.uuid4().hex[:5]}",
            "phone": "+375291110099",
            "city_id": cid,
            "description": "d" * 40,
            "education": "Высшее",
            "experience_years": 4,
            "session_duration_minutes": 45,
            "min_hours_before_booking": 3,
        },
        service_ids=[sid],
        arena_ids=[aid],
    )
    await db_session.execute(
        text("INSERT INTO trainer_photos (trainer_id, file_key, sort_order) VALUES (:t, :fk, 0)"),
        {"t": tid, "fk": f"trainers/{tid}/a.jpg"},
    )
    tg = _fresh_trainer_telegram_id()
    await db_session.execute(
        text("UPDATE trainers SET telegram_id = :tg, status = 'active' WHERE id = :t"),
        {"tg": tg, "t": tid},
    )
    await db_session.commit()
    if published:
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PENDING_REVIEW,
            reason=REASON_TRAINER_SUBMITTED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )
        await set_catalog_state(
            db_session, tid, CATALOG_STATE_PUBLISHED,
            reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
        )
    return tid, tg


async def _get(tg: int) -> dict:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/webapp/trainer/catalog", headers=HEADERS)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _post(tg: int, path: str) -> tuple[int, dict]:
    with patch_trainer_init_auth(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(f"/api/webapp/trainer/catalog/{path}", headers=HEADERS)
    try:
        return resp.status_code, resp.json()
    except Exception:  # noqa: BLE001
        return resp.status_code, {}


@pytest.mark.asyncio
async def test_draft_screen_explains_the_catalog_and_offers_to_publish(app_use_test_db, db_session) -> None:
    _, tg = await _complete_trainer(db_session)
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_DRAFT
    assert body["headline"] and body["body"]
    assert "submit" in body["actions"]
    # The fear this line exists to remove.
    assert "подписка" in body["subscription_note"].lower()


@pytest.mark.asyncio
async def test_published_screen_carries_preview_and_history(app_use_test_db, db_session) -> None:
    _, tg = await _complete_trainer(db_session, published=True)
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_PUBLISHED
    assert body["actions"] == ["hide"]
    preview = body["preview"]
    assert preview["first_name"] == "Карточка"
    assert preview["city_name"]
    assert preview["photo_file_key"]
    # History is what makes «следить, что я в каталоге» possible at all.
    assert [e["to_state"] for e in body["events"]][:2] == [
        CATALOG_STATE_PUBLISHED,
        CATALOG_STATE_PENDING_REVIEW,
    ]


@pytest.mark.asyncio
async def test_submit_requires_a_complete_card_and_reports_gaps(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)
    await db_session.execute(
        text("UPDATE trainer_profiles SET phone = '' WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    status, body = await _post(tg, "submit")
    assert status == 422
    detail = body["detail"]
    assert "phone" in (detail.get("missing_fields") or [])
    assert any("телефон" in label for label in detail.get("missing_labels_ru") or [])


@pytest.mark.asyncio
async def test_submit_then_hide_then_restore_round_trip(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)

    status, body = await _post(tg, "submit")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_PENDING_REVIEW
    assert body["actions"] == ["withdraw"]

    # A moderator approves; then the trainer takes it down and puts it back.
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_PUBLISHED,
        reason=REASON_MODERATOR_APPROVED, actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )
    status, body = await _post(tg, "hide")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_HIDDEN

    status, body = await _post(tg, "restore")
    assert status == 200, body
    # Straight back, no second review: the dialog promises exactly this.
    assert body["state"] == CATALOG_STATE_PUBLISHED


@pytest.mark.asyncio
async def test_restore_from_paused_returns_422_while_the_gap_is_open(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text("UPDATE trainer_profiles SET phone = '' WHERE trainer_id = :t"), {"t": tid}
    )
    await set_catalog_state(
        db_session, tid, CATALOG_STATE_PAUSED,
        reason="missing_fields", actor_type=CATALOG_ACTOR_MODERATOR, notify=False,
    )
    await db_session.commit()
    status, body = await _post(tg, "restore")
    assert status == 422
    assert "phone" in (body["detail"].get("missing_fields") or [])


@pytest.mark.asyncio
async def test_withdraw_clears_the_queue_stamp(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session)
    await _post(tg, "submit")
    status, body = await _post(tg, "withdraw")
    assert status == 200, body
    assert body["state"] == CATALOG_STATE_DRAFT
    r = await db_session.execute(
        text("SELECT moderation_submitted_at FROM trainers WHERE id = :t"), {"t": tid}
    )
    assert r.scalar() is None


@pytest.mark.asyncio
async def test_pending_revision_shows_both_versions_and_can_be_cancelled(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text(
            "UPDATE trainers SET photo_pending = CAST(:js AS jsonb) WHERE id = :t"
        ),
        {"t": tid, "js": json.dumps({"file_key": f"trainers/{tid}/new.jpg"})},
    )
    await db_session.commit()

    body = await _get(tg)
    revision = body["revision"]
    assert revision is not None and revision["has_photo"] is True
    # The thing the trainer could never see before: what clients are looking at *right now*.
    assert revision["current"]["photo_file_key"] != revision["next"]["photo_file_key"]
    assert body["state"] == CATALOG_STATE_PUBLISHED, "a pending edit must not unpublish the card"

    status, after = await _post(tg, "cancel-revision")
    assert status == 200, after
    assert after["revision"] is None


@pytest.mark.asyncio
async def test_hidden_arenas_warn_without_unpublishing(app_use_test_db, db_session) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    await db_session.execute(
        text("UPDATE trainer_arenas SET is_public = false WHERE trainer_id = :t"), {"t": tid}
    )
    await db_session.commit()
    body = await _get(tg)
    assert body["state"] == CATALOG_STATE_PUBLISHED
    codes = {w["code"] for w in body["warnings"]}
    assert "no_public_arenas" in codes


@pytest.mark.asyncio
async def test_studio_managed_trainer_gets_a_read_only_screen(app_use_test_db, db_session, monkeypatch) -> None:
    tid, tg = await _complete_trainer(db_session, published=True)
    monkeypatch.setattr(
        "src.application.trainer_catalog_view.get_effective_studio_access_mode",
        lambda *a, **kw: _async_value("studio_admin_only"),
    )
    body = await _get(tg)
    assert body["can_act"] is False
    assert body["managed_by_studio"] is True
    assert body["actions"] == []
    status, _ = await _post(tg, "hide")
    assert status == 403


def _async_value(value):
    async def _inner():
        return value

    return _inner()
