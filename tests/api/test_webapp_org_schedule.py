"""TASK-141 (S6): Org schedule endpoints — multi-trainer schedule management.

Tests cover:
- GET /api/webapp/org/schedule — load schedule for a trainer in the collective
- POST /api/webapp/org/schedule/slots — create/update slots (owner only)
- DELETE /api/webapp/org/schedule/slots/{id} — delete slot (owner only)
- GET /api/webapp/org/schedule/templates — weekly template entries
- PUT /api/webapp/org/schedule/templates/day — save template for a weekday (owner only)
- POST /api/webapp/org/schedule/apply-week — apply template to a week (owner only)
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.application.collective_use_cases import (
    consume_collective_claim_token_for_operator,
    consume_collective_invite_token,
    create_collective_draft,
    issue_collective_claim_token,
)

pytestmark = pytest.mark.collective


@contextmanager
def patch_org_webapp_init(telegram_id: int) -> Iterator[None]:
    fake = MiniAppPrincipal(platform=MiniAppPlatform.TELEGRAM, user_id=telegram_id)
    with patch("src.api.miniapp_auth.deps.verify_telegram_init_data_principal", return_value=fake):
        yield


async def _claim_school(db_session, *, slug: str, telegram_id: int) -> int:
    created = await create_collective_draft(db_session, slug=slug, display_name=slug)
    claim = await issue_collective_claim_token(db_session, int(created["id"]))
    outcome = await consume_collective_claim_token_for_operator(db_session, claim["token"], telegram_id)
    assert outcome.error is None
    return int(created["id"])


async def _create_trainer(db_session, telegram_id: int) -> int:
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, telegram_id, studio_access_mode, created_at) "
            "VALUES ('active', :tgid, 'full_trainer', :now) RETURNING id"
        ),
        {"tgid": telegram_id, "now": datetime.now(timezone.utc)},
    )
    return int(r.scalar_one())


async def _add_trainer_to_collective(db_session, collective_id: int, trainer_id: int) -> None:
    """Add trainer as active member of the collective."""
    await db_session.execute(
        text(
            "INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at) "
            "VALUES (:cid, :tid, 'member', 'active', now())"
        ),
        {"cid": collective_id, "tid": trainer_id},
    )
    await db_session.commit()


async def _grant_crm_subscription(db_session, trainer_id: int) -> None:
    r = await db_session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
    plan_id = r.scalar()
    if plan_id is None:
        pytest.skip("need subscription_plans in DB")
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=400)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES
                (:tid, :pid, 'crm', 1, :st, :exp, 'active')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "st": now, "exp": exp},
    )
    await db_session.commit()


async def _insert_slot(
    db_session,
    trainer_id: int,
    slot_date: date,
    start_h: int,
    end_h: int,
    status: str = "available",
) -> int:
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :en, :status, 1)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "d": slot_date,
            "st": time(start_h, 0),
            "en": time(end_h, 0),
            "status": status,
        },
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_org_schedule_get_returns_slots_for_trainer(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_001
    collective_id = await _claim_school(db_session, slug="org-sched-get", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    await _insert_slot(db_session, trainer_id, monday, 10, 11)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["trainer_id"] == trainer_id
    assert len(body["slots"]) == 1
    assert body["slots"][0]["start_time"] == "10:00"


@pytest.mark.asyncio
async def test_org_schedule_get_404_for_trainer_not_in_collective(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_002
    await _claim_school(db_session, slug="org-sched-404", telegram_id=telegram_id)
    outsider_trainer_id = await _create_trainer(db_session, telegram_id + 1)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={outsider_trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_schedule_get_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/webapp/org/schedule?trainer_id=1")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_org_schedule_post_slots_creates_slot(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_003
    collective_id = await _claim_school(db_session, slug="org-sched-post", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    slot_date = monday.isoformat()

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "slot_date": slot_date,
                    "start_times": ["10:00", "11:00"],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["trainer_id"] == trainer_id

    # Verify slots were created
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    assert len(body["slots"]) == 2


@pytest.mark.asyncio
async def test_org_schedule_post_slots_forbidden_for_admin(app_use_test_db, db_session) -> None:
    owner_tgid = 8_600_000_004
    admin_tgid = 8_600_000_005
    collective_id = await _claim_school(db_session, slug="org-sched-admin", telegram_id=owner_tgid)
    trainer_id = await _create_trainer(db_session, owner_tgid + 100)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    await db_session.execute(
        text(
            "INSERT INTO collective_operators (collective_id, telegram_id, role, status, created_at, updated_at) "
            "VALUES (:cid, :tgid, 'admin', 'active', now(), now())"
        ),
        {"cid": collective_id, "tgid": admin_tgid},
    )
    await db_session.commit()

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    with patch_org_webapp_init(admin_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "slot_date": monday.isoformat(),
                    "start_times": ["10:00"],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_schedule_post_slots_401_without_init_data(app_use_test_db) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webapp/org/schedule/slots",
            json={"trainer_id": 1, "slot_date": "2026-01-01", "start_times": ["10:00"]},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_org_schedule_delete_slot(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_006
    collective_id = await _claim_school(db_session, slug="org-sched-del", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    slot_id = await _insert_slot(db_session, trainer_id, monday, 10, 11)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/webapp/org/schedule/slots/{slot_id}?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200

    # Verify slot was deleted
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    assert len(body["slots"]) == 0


@pytest.mark.asyncio
async def test_org_schedule_delete_slot_forbidden_for_admin(app_use_test_db, db_session) -> None:
    owner_tgid = 8_600_000_007
    admin_tgid = 8_600_000_008
    collective_id = await _claim_school(db_session, slug="org-sched-del-admin", telegram_id=owner_tgid)
    trainer_id = await _create_trainer(db_session, owner_tgid + 100)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    await db_session.execute(
        text(
            "INSERT INTO collective_operators (collective_id, telegram_id, role, status, created_at, updated_at) "
            "VALUES (:cid, :tgid, 'admin', 'active', now(), now())"
        ),
        {"cid": collective_id, "tgid": admin_tgid},
    )
    await db_session.commit()

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    slot_id = await _insert_slot(db_session, trainer_id, monday, 10, 11)

    with patch_org_webapp_init(admin_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                f"/api/webapp/org/schedule/slots/{slot_id}?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_schedule_get_templates(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_009
    collective_id = await _claim_school(db_session, slug="org-sched-tpl", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule/templates?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["trainer_id"] == trainer_id
    assert "templates" in body


@pytest.mark.asyncio
async def test_org_schedule_put_template_day(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_010
    collective_id = await _claim_school(db_session, slug="org-sched-tpl-put", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 0,
                    "start_hours": [10, 11, 12],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 200

    # Verify template was saved
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule/templates?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    monday_templates = [t for t in body["templates"] if t["day_of_week"] == 0]
    assert len(monday_templates) == 3


@pytest.mark.asyncio
async def test_org_schedule_put_template_day_forbidden_for_admin(app_use_test_db, db_session) -> None:
    owner_tgid = 8_600_000_011
    admin_tgid = 8_600_000_012
    collective_id = await _claim_school(db_session, slug="org-sched-tpl-admin", telegram_id=owner_tgid)
    trainer_id = await _create_trainer(db_session, owner_tgid + 100)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    await db_session.execute(
        text(
            "INSERT INTO collective_operators (collective_id, telegram_id, role, status, created_at, updated_at) "
            "VALUES (:cid, :tgid, 'admin', 'active', now(), now())"
        ),
        {"cid": collective_id, "tgid": admin_tgid},
    )
    await db_session.commit()

    with patch_org_webapp_init(admin_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 0,
                    "start_hours": [10],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_schedule_apply_week(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_013
    collective_id = await _claim_school(db_session, slug="org-sched-apply", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    # First set a template for Monday
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 0,
                    "start_hours": [10, 11],
                    "duration_minutes": 60,
                },
            )

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/schedule/apply-week",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "week_start": monday.isoformat(),
                },
            )
    assert resp.status_code == 200

    # Verify slots were created for Monday
    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    body = resp.json()
    monday_slots = [s for s in body["slots"] if s["slot_date"] == monday.isoformat()]
    assert len(monday_slots) == 2


@pytest.mark.asyncio
async def test_org_schedule_apply_week_forbidden_for_admin(app_use_test_db, db_session) -> None:
    owner_tgid = 8_600_000_014
    admin_tgid = 8_600_000_015
    collective_id = await _claim_school(db_session, slug="org-sched-apply-admin", telegram_id=owner_tgid)
    trainer_id = await _create_trainer(db_session, owner_tgid + 100)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    await db_session.execute(
        text(
            "INSERT INTO collective_operators (collective_id, telegram_id, role, status, created_at, updated_at) "
            "VALUES (:cid, :tgid, 'admin', 'active', now(), now())"
        ),
        {"cid": collective_id, "tgid": admin_tgid},
    )
    await db_session.commit()

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    with patch_org_webapp_init(admin_tgid):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/schedule/apply-week",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "week_start": monday.isoformat(),
                },
            )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_org_schedule_services_lists_only_trainer_own_services(app_use_test_db, db_session) -> None:
    """TASK-144 S1: group-slot service picker — only services this trainer actually offers."""
    telegram_id = 8_600_000_050
    collective_id = await _claim_school(db_session, slug="org-sched-services", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)

    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 2"))
    service_ids = [row[0] for row in r.fetchall()]
    if len(service_ids) < 2:
        pytest.skip("need at least 2 seed services")
    own_service_id, other_service_id = service_ids[0], service_ids[1]
    await db_session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id) VALUES (:tid, :sid)"),
        {"tid": trainer_id, "sid": own_service_id},
    )
    await db_session.commit()

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule/services?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert own_service_id in ids
    assert other_service_id not in ids


@pytest.mark.asyncio
async def test_org_schedule_services_requires_trainer_in_collective(app_use_test_db, db_session) -> None:
    telegram_id = 8_600_000_051
    await _claim_school(db_session, slug="org-sched-services-outside", telegram_id=telegram_id)
    outsider_trainer_id = await _create_trainer(db_session, telegram_id + 1)
    # Not added to the collective.

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                f"/api/webapp/org/schedule/services?trainer_id={outsider_trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_org_schedule_post_slots_preserves_existing_when_included(
    app_use_test_db, db_session
) -> None:
    """Locks in the contract org-schedule-main.js's grid relies on: POST slots ``start_times``
    is a full replace of the day's available slots — the client MUST union existing + new or
    it silently deletes whatever isn't listed (see TASK-144 S1 Comprehension Tips)."""
    telegram_id = 8_600_000_052
    collective_id = await _claim_school(db_session, slug="org-sched-preserve", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    today = date.today()
    monday = today - timedelta(days=today.weekday())
    await _insert_slot(db_session, trainer_id, monday, 10, 11)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/org/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "slot_date": monday.isoformat(),
                    "start_times": ["10:00", "14:00"],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 200

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get_resp = await client.get(
                f"/api/webapp/org/schedule?trainer_id={trainer_id}"
                f"&from_date={monday.isoformat()}&to_date={monday.isoformat()}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    times = sorted(s["start_time"] for s in get_resp.json()["slots"])
    assert times == ["10:00", "14:00"]


@pytest.mark.asyncio
async def test_org_schedule_put_template_day_with_slots_array(app_use_test_db, db_session) -> None:
    """org-schedule-main.js's template editor sends ``slots`` (minute-precision), not the
    ``start_hours`` convenience field the other template test uses — cover that path directly."""
    telegram_id = 8_600_000_053
    collective_id = await _claim_school(db_session, slug="org-sched-tpl-slots", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 2,
                    "duration_minutes": 45,
                    "slots": [
                        {"hour": 9, "minute": 30, "capacity": 1},
                        {"hour": 14, "minute": 0, "capacity": 1},
                    ],
                },
            )
    assert resp.status_code == 200

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get_resp = await client.get(
                f"/api/webapp/org/schedule/templates?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    wed_templates = sorted(
        t["start_time"] for t in get_resp.json()["templates"] if t["day_of_week"] == 2
    )
    assert wed_templates == ["09:30", "14:00"]


@pytest.mark.asyncio
async def test_org_schedule_put_template_day_empty_slots_clears_day(app_use_test_db, db_session) -> None:
    """Re-saving with an empty ``slots`` array — org-schedule-main.js's toggle-off-everything
    case — must clear that weekday's template (full replace, per replace_templates_for_day)."""
    telegram_id = 8_600_000_054
    collective_id = await _claim_school(db_session, slug="org-sched-tpl-clear", telegram_id=telegram_id)
    trainer_id = await _create_trainer(db_session, telegram_id + 1)
    await _add_trainer_to_collective(db_session, collective_id, trainer_id)
    await _grant_crm_subscription(db_session, trainer_id)

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            first = await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 3,
                    "duration_minutes": 45,
                    "slots": [{"hour": 9, "minute": 0, "capacity": 1}],
                },
            )
            assert first.status_code == 200
            second = await client.put(
                "/api/webapp/org/schedule/templates/day",
                headers={"X-Telegram-Init-Data": "mock"},
                json={
                    "trainer_id": trainer_id,
                    "day_of_week": 3,
                    "duration_minutes": 45,
                    "slots": [],
                },
            )
    assert second.status_code == 200

    with patch_org_webapp_init(telegram_id):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            get_resp = await client.get(
                f"/api/webapp/org/schedule/templates?trainer_id={trainer_id}",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    thu_templates = [t for t in get_resp.json()["templates"] if t["day_of_week"] == 3]
    assert thu_templates == []
