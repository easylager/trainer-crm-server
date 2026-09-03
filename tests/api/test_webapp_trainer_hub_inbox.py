"""Wave B: hub inbox-count, bootstrap action_inbox, confirm-batch."""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.trainer_feature_moments import ITEM_RECURRING_CLIENT
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    _insert_slot,
    patch_trainer_webapp_init,
)
from tests.db_catalog_helpers import require_seed_service_id


async def _insert_pending_booking(db_session, trainer_id: int) -> int:
    service_id = await require_seed_service_id(db_session)
    slot_date = date.today() + timedelta(days=2)
    r_slot = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :sd, '10:00', '11:00', 'booked')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "sd": slot_date},
    )
    slot_id = int(r_slot.scalar_one())
    tg = 8_000_000_000 + (uuid.uuid4().int % 1_000_000_000)
    r_client = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone)
            VALUES (:tg, 'Inbox', 'Client', '+375291234567')
            RETURNING id
            """
        ),
        {"tg": tg},
    )
    client_id = int(r_client.scalar_one())
    r_book = await db_session.execute(
        text(
            """
            INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
            VALUES (:tid, :cid, :sid, :svc, 'pending')
            RETURNING id
            """
        ),
        {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
    )
    booking_id = int(r_book.scalar_one())
    await db_session.commit()
    return booking_id


@pytest.mark.asyncio
async def test_hub_inbox_count_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/trainer/hub/inbox-count")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_hub_inbox_count_returns_badges(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/inbox-count",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "badges" in data
    assert set(data["badges"].keys()) == {
        "schedule",
        "center",
        "more",
        "clients",
        "menu",
        "menu_hints",
    }
    assert isinstance(data["badges"]["menu"], dict)
    assert isinstance(data["badges"]["menu_hints"], dict)
    assert isinstance(data["total_actionable"], int)


@pytest.mark.asyncio
async def test_hub_bootstrap_includes_action_inbox(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    data = resp.json()
    assert "action_inbox" in data
    assert data["action_inbox"] is not None
    assert "items" in data["action_inbox"]
    assert "badges" in data["action_inbox"]


@pytest.mark.asyncio
async def test_hub_bootstrap_pending_inbox_includes_booking_ids(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    bid = await _insert_pending_booking(db_session, trainer_id)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=1",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    inbox = resp.json()["action_inbox"]
    pending = next((it for it in inbox["items"] if it["id"] == "pending_bookings"), None)
    assert pending is not None
    assert pending["count"] == 1
    assert bid in (pending.get("booking_ids") or [])


@pytest.mark.asyncio
async def test_hub_inbox_event_records_audit(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/inbox-event",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "event": "inbox_item_shown",
                    "surface": "hub",
                    "item_id": "pending_bookings",
                    "kind": "pending",
                    "count": 2,
                },
            )
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event",
    [
        "hint_clicked",
        "hint_dismissed",
        "next_step_shown",
        "next_step_clicked",
        "next_step_dismissed",
    ],
)
async def test_hub_inbox_event_accepts_task_028_event_types(
    app_use_test_db, db_session, event: str
) -> None:
    """TASK-028: showed→clicked/dismissed pairing needs these event types allowed."""
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/inbox-event",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"event": event, "surface": "hub", "item_id": "share_link"},
            )
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


@pytest.mark.asyncio
async def test_hub_inbox_event_rejects_unknown_event(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/inbox-event",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"event": "made_up_event", "surface": "hub"},
            )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_rhythm_hint_dismiss_snoozes_a_dismissible_hint(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/rhythm-hint/dismiss",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"hint_id": "referral_growth"},
            )
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


@pytest.mark.asyncio
@pytest.mark.parametrize("hint_id", ["open_loop_no_next", "slots_this_week", "made_up_hint"])
async def test_rhythm_hint_dismiss_rejects_urgent_and_unknown(
    app_use_test_db, db_session, hint_id: str
) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/hub/rhythm-hint/dismiss",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"hint_id": hint_id},
            )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_dismissed_rhythm_hint_disappears_from_bootstrap_end_to_end(
    app_use_test_db, db_session
) -> None:
    """
    TASK-029 AC-001/AC-003 end-to-end: real dismiss endpoint → real snooze row →
    real bootstrap response no longer contains the hint — no localStorage involved anywhere.
    """
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    # has_future_slots=True, weekly_template_count stays 0 → the "template" rhythm hint fires.
    await _insert_slot(db_session, trainer_id, date.today() + timedelta(days=2), 10, 11)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            before = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            before_ids = {it["id"] for it in before.json()["action_inbox"]["items"]}
            assert "template" in before_ids

            dismiss_resp = await client.post(
                "/api/webapp/trainer/hub/rhythm-hint/dismiss",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"hint_id": "template"},
            )
            assert dismiss_resp.status_code == 200

            after = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            after_ids = {it["id"] for it in after.json()["action_inbox"]["items"]}
            assert "template" not in after_ids

            inbox_count = await client.get(
                "/api/webapp/trainer/hub/inbox-count",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert inbox_count.status_code == 200


async def _insert_recurring_pattern_bookings(db_session, trainer_id: int) -> None:
    """3 confirmed bookings, same client/weekday/time, 3 different weeks — TASK-030 fact."""
    service_id = await require_seed_service_id(db_session)
    tg = 8_100_000_000 + (uuid.uuid4().int % 1_000_000_000)
    r_client = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone)
            VALUES (:tg, 'Recurring', 'Client', '+375291234568')
            RETURNING id
            """
        ),
        {"tg": tg},
    )
    client_id = int(r_client.scalar_one())
    friday = date.today() - timedelta(days=(date.today().weekday() - 4) % 7)
    for i in range(3):
        d = friday - timedelta(days=7 * i)
        r_slot = await db_session.execute(
            text(
                """
                INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
                VALUES (:tid, :d, '18:00', '19:00', 'booked') RETURNING id
                """
            ),
            {"tid": trainer_id, "d": d},
        )
        slot_id = int(r_slot.scalar_one())
        await db_session.execute(
            text(
                """
                INSERT INTO bookings (trainer_id, client_id, slot_id, service_id, status)
                VALUES (:tid, :cid, :sid, :svc, 'confirmed')
                """
            ),
            {"tid": trainer_id, "cid": client_id, "sid": slot_id, "svc": service_id},
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_feature_moment_card_appears_in_bootstrap_end_to_end(app_use_test_db, db_session) -> None:
    """TASK-030 AC-001/AC-009: real bookings → real card in bootstrap → telemetry accepted."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await _insert_recurring_pattern_bookings(db_session, trainer_id)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert resp.status_code == 200
            items = resp.json()["action_inbox"]["items"]
            card = next((it for it in items if it["id"] == ITEM_RECURRING_CLIENT), None)
            assert card is not None
            assert "Recurring" in (card["title"] + card["subtitle"])
            assert card["kind"] == "rhythm"
            assert card["dismissible"] is True

            click_resp = await client.post(
                "/api/webapp/trainer/hub/inbox-event",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"event": "hint_clicked", "surface": "hub", "item_id": ITEM_RECURRING_CLIENT},
            )
            assert click_resp.status_code == 200
            assert click_resp.json().get("ok") is True


@pytest.mark.asyncio
async def test_feature_moment_card_dismiss_snoozes_for_30_days_end_to_end(
    app_use_test_db, db_session
) -> None:
    """TASK-030 EDGE-003: отказ снузит надолго через тот же сервер, что TASK-029."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await _insert_recurring_pattern_bookings(db_session, trainer_id)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            before = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            before_ids = {it["id"] for it in before.json()["action_inbox"]["items"]}
            assert ITEM_RECURRING_CLIENT in before_ids

            dismiss_resp = await client.post(
                "/api/webapp/trainer/hub/rhythm-hint/dismiss",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"hint_id": ITEM_RECURRING_CLIENT},
            )
            assert dismiss_resp.status_code == 200

            after = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            after_ids = {it["id"] for it in after.json()["action_inbox"]["items"]}
            assert ITEM_RECURRING_CLIENT not in after_ids

    r = await db_session.execute(
        text(
            "SELECT snooze_until FROM trainer_hint_dismissals WHERE trainer_id = :tid AND hint_id = :hid"
        ),
        {"tid": trainer_id, "hid": ITEM_RECURRING_CLIENT},
    )
    snooze_until = r.scalar_one()
    assert (snooze_until - datetime.now(timezone.utc)).days >= 29


async def _expire_trial_so_trainer_is_in_lead_mode(db_session, trainer_id: int) -> None:
    """
    `with_crm=False` alone is not Lead Mode: `ensure_trainer_welcome_trial` (called on every
    bootstrap) lazily grants a fresh trial to any trainer who never had one. Genuine Lead Mode —
    the state ``has_crm_subscription_access`` actually resolves False for — requires a trial
    already used up and expired, mirroring `test_lead_mode_recovery.py`'s `_insert_expired_sub`.
    """
    r = await db_session.execute(text("SELECT id, period_days FROM subscription_plans WHERE is_trial = true LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("No trial plan seeded — run migrations")
    plan_id = int(row[0])
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, modules, started_at, expires_at, status)
            VALUES (:tid, :pid, 'crm', '{}'::jsonb, now() - interval '30 days', now() - interval '1 day', 'trial')
            """
        ),
        {"tid": trainer_id, "pid": plan_id},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_feature_moment_card_absent_for_lead_mode_trainer_end_to_end(
    app_use_test_db, db_session
) -> None:
    """TASK-030 AC-007 at the endpoint level: expired trial (genuine Lead Mode) → no education card."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=False)
    await _expire_trial_so_trainer_is_in_lead_mode(db_session, trainer_id)
    await _insert_recurring_pattern_bookings(db_session, trainer_id)

    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/hub/bootstrap?bookings_limit=10",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    items = resp.json()["action_inbox"]["items"]
    assert ITEM_RECURRING_CLIENT not in {it["id"] for it in items}


@pytest.mark.asyncio
async def test_confirm_batch_confirms_pending(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    bid = await _insert_pending_booking(db_session, trainer_id)
    with patch_trainer_webapp_init(tg), patch(
        "src.api.routes.webapp.notify_client_booking_confirmed_by_trainer",
        new=AsyncMock(),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/bookings/confirm-batch",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"booking_ids": [bid]},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["confirmed_count"] == 1
    assert bid in body["confirmed"]
    r = await db_session.execute(text("SELECT status FROM bookings WHERE id = :id"), {"id": bid})
    assert r.scalar_one() == "confirmed"
