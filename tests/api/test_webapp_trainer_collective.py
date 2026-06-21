"""API tests for trainer collective studio — brand, governance, billing (Wave P1–P2)."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from tests.api.collective_api_helpers import seed_active_collective_member, seed_active_collective_owner
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)

pytestmark = pytest.mark.collective


@pytest.mark.asyncio
async def test_collective_get_endpoints_disabled_without_feature_flag(
    app_use_test_db, db_session, monkeypatch
) -> None:
    monkeypatch.setenv("TRAINER_COLLECTIVE_ENABLED", "0")
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            collective = await client.get(
                "/api/webapp/trainer/collective",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            notice = await client.get(
                "/api/webapp/trainer/collective/suspended-notice",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert collective.status_code == 200
    assert collective.json() == {"enabled": False}
    assert notice.status_code == 200
    assert notice.json() == {"suspended": False, "enabled": False}


@pytest.mark.asyncio
async def test_patch_collective_brand_owner(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(db_session, trainer_id)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/trainer/collective",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"display_name": "Renamed Studio", "tagline": "New pitch"},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Renamed Studio"
    assert body["tagline"] == "New pitch"
    assert body["can_edit_brand"] is True


@pytest.mark.asyncio
async def test_patch_collective_brand_404_solo(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    await _create_active_trainer(db_session, tg, with_crm=True)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/api/webapp/trainer/collective",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"display_name": "Nope"},
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_collective_studio_pending_profile_owner(app_use_test_db, db_session) -> None:
    """Claim via bot often leaves trainer in pending_profile — studio must still resolve."""
    tg = _fresh_trainer_telegram_id()
    r = await db_session.execute(
        text(
            """
            INSERT INTO trainers (status, telegram_id, created_at)
            VALUES ('pending_profile', :tg, NOW())
            RETURNING id
            """
        ),
        {"tg": tg},
    )
    trainer_id = int(r.scalar_one())
    await seed_active_collective_owner(db_session, trainer_id, slug="pending-owner")
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/collective",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    assert resp.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_get_collective_studio_includes_subscription_checkout(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(db_session, trainer_id, slug="checkout-ui")
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/webapp/trainer/collective",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    checkout = resp.json().get("subscription_checkout") or {}
    assert checkout.get("checkout_mode")
    assert len(checkout.get("pricing") or []) == 3


@pytest.mark.asyncio
async def test_remove_collective_member_api(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    owner_id = await _create_active_trainer(db_session, tg, with_crm=True)
    cid = await seed_active_collective_owner(db_session, owner_id, slug="gov-remove")
    member_id = await seed_active_collective_member(db_session, cid)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                f"/api/webapp/trainer/collective/members/{member_id}/remove",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert resp.status_code == 200
    studio = resp.json().get("studio") or {}
    member_ids = [m["trainer_id"] for m in studio.get("members") or [] if m.get("status") == "active"]
    assert member_id not in member_ids


@pytest.mark.asyncio
async def test_transfer_collective_ownership_api(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    owner_id = await _create_active_trainer(db_session, tg, with_crm=True)
    cid = await seed_active_collective_owner(db_session, owner_id, slug="gov-transfer")
    member_id = await seed_active_collective_member(db_session, cid)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/collective/transfer-ownership",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"new_owner_trainer_id": member_id},
            )
    assert resp.status_code == 200
    studio = resp.json().get("studio") or {}
    assert studio.get("role") == "member"
    owner_row = next(
        (m for m in studio.get("members") or [] if m.get("trainer_id") == member_id),
        None,
    )
    assert owner_row is not None
    assert owner_row.get("role") == "owner"


@pytest.mark.asyncio
async def test_revoke_collective_invites_api(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    owner_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(db_session, owner_id, slug="gov-revoke")
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            invite_resp = await client.post(
                "/api/webapp/trainer/collective/invite",
                headers={"X-Telegram-Init-Data": "mock"},
            )
            assert invite_resp.status_code == 200
            revoke_resp = await client.post(
                "/api/webapp/trainer/collective/revoke-invites",
                headers={"X-Telegram-Init-Data": "mock"},
            )
    assert revoke_resp.status_code == 200
    assert int(revoke_resp.json().get("revoked_count") or 0) >= 1


@pytest.mark.asyncio
async def test_collective_mock_checkout_activates_pool(
    app_use_test_db,
    db_session,
    monkeypatch,
) -> None:
    class _SandboxSettings:
        payment_sandbox = True

    monkeypatch.setattr("src.api.routes.webapp.Settings", _SandboxSettings)

    tg = _fresh_trainer_telegram_id()
    owner_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(db_session, owner_id, slug="bill-mock")
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/collective/subscription/mock-checkout",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"period_months": 1},
            )
    assert resp.status_code == 200
    studio = resp.json().get("studio") or {}
    pool = studio.get("subscription_pool") or {}
    assert pool.get("active") is True


@pytest.mark.asyncio
async def test_collective_invoice_request_owner_only(app_use_test_db, db_session, monkeypatch) -> None:
    class _InvoiceSettings:
        payment_sandbox = False
        trainer_subscription_checkout_mode = "invoice"

        def resolved_trainer_subscription_checkout_mode(self):
            return "invoice"

    monkeypatch.setattr("src.api.routes.webapp.Settings", _InvoiceSettings)
    monkeypatch.setattr(
        "src.application.collective_invoice_admin_notify.notify_admins_new_collective_subscription_invoice",
        lambda _iid: None,
    )

    tg = _fresh_trainer_telegram_id()
    owner_id = await _create_active_trainer(db_session, tg, with_crm=True)
    await seed_active_collective_owner(db_session, owner_id, slug="bill-invoice")
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/trainer/collective/subscription/invoice-request",
                headers={"X-Telegram-Init-Data": "mock"},
                json={"period_months": 1},
            )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("invoice_id")
    studio = body.get("studio") or {}
    pending = (studio.get("subscription_checkout") or {}).get("pending_invoice")
    assert pending is not None
    assert pending.get("invoice_id") == body["invoice_id"]
