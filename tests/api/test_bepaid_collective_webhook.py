"""bePaid webhook: collective pool invoice tracking_id colinv_{id}."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.collective_use_cases import (
    COLLECTIVE_STATUS_ACTIVE,
    MEMBER_ROLE_OWNER,
    MEMBER_STATUS_ACTIVE,
    create_collective_subscription_invoice,
    get_collective_subscription_status,
)

pytestmark = pytest.mark.collective


async def _seed_owner_studio(db_session, *, slug: str = "wh-col") -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (slug, display_name, status, seat_limit, created_at, updated_at)
            VALUES (:slug, 'Webhook Studio', :st, 5, :now, :now)
            RETURNING id
            """
        ),
        {"slug": slug, "st": COLLECTIVE_STATUS_ACTIVE, "now": now},
    )
    cid = int(r.scalar_one())
    r_tr = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    tid = int(r_tr.scalar_one())
    await db_session.execute(
        text("UPDATE collectives SET owner_trainer_id = :tid WHERE id = :cid"),
        {"tid": tid, "cid": cid},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, :role, :active, :now)
            """
        ),
        {
            "cid": cid,
            "tid": tid,
            "role": MEMBER_ROLE_OWNER,
            "active": MEMBER_STATUS_ACTIVE,
            "now": now,
        },
    )
    await db_session.commit()
    return cid, tid


@pytest.mark.asyncio
async def test_bepaid_webhook_confirms_collective_invoice(app_use_test_db, db_session) -> None:
    cid, tid = await _seed_owner_studio(db_session, slug="wh-confirm")
    inv = await create_collective_subscription_invoice(
        db_session,
        collective_id=cid,
        requested_by_trainer_id=tid,
        period_months=1,
    )
    assert inv is not None
    invoice_id = int(inv["invoice_id"])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/webhooks/bepaid",
            json={
                "transaction": {
                    "status": "successful",
                    "tracking_id": f"colinv_{invoice_id}",
                    "uid": "test-colinv-uid-1",
                }
            },
        )
    assert resp.status_code == 200

    status = await get_collective_subscription_status(db_session, collective_id=cid)
    assert status is not None
    assert status.get("active_subscription") is not None
