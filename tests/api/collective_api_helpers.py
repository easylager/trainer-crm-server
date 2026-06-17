"""Shared helpers for collective / studio API tests."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.collective


async def seed_active_collective_owner(
    db_session: AsyncSession,
    trainer_id: int,
    *,
    slug: str = "api-col-studio",
    seats: int = 5,
    schedule_mode: str = "member_autonomous",
    organization_format: str = "studio",
    owner_studio_access_mode: str = "full_trainer",
) -> int:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            """
            INSERT INTO collectives (
                slug, display_name, status, seat_limit, owner_trainer_id,
                schedule_mode, organization_format, owner_studio_access_mode,
                created_at, updated_at
            )
            VALUES (
                :slug, 'API Studio', 'active', :seats, :tid,
                :mode, :org_fmt, :owner_mode, :now, :now
            )
            RETURNING id
            """
        ),
        {
            "slug": slug,
            "tid": trainer_id,
            "seats": seats,
            "mode": schedule_mode,
            "org_fmt": organization_format,
            "owner_mode": owner_studio_access_mode,
            "now": now,
        },
    )
    cid = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, 'owner', 'active', :now)
            """
        ),
        {"cid": cid, "tid": trainer_id, "now": now},
    )
    await db_session.commit()
    return cid


async def seed_active_collective_member(
    db_session: AsyncSession,
    collective_id: int,
) -> int:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text("INSERT INTO trainers (status, created_at) VALUES ('active', :now) RETURNING id"),
        {"now": now},
    )
    member_id = int(r.scalar_one())
    await db_session.execute(
        text(
            """
            INSERT INTO collective_members (collective_id, trainer_id, role, status, joined_at)
            VALUES (:cid, :tid, 'member', 'active', :now)
            """
        ),
        {"cid": collective_id, "tid": member_id, "now": now},
    )
    await db_session.commit()
    return member_id
