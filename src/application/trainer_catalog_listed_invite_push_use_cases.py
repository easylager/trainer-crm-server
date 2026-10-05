"""
One-time Telegram push after a trainer's card is first in the catalog and they still have
no confirmed/completed real bookings — invite link + support CTA.

Delayed a few hours after ``catalog_state_changed_at`` so it does not land in the same
minute as the moderator «анкета принята» push.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import CATALOG_STATE_PUBLISHED, TRAINER_STATUS_DEACTIVATED

# Hours after listing before we nudge (moderation push usually fires immediately).
CATALOG_LISTED_INVITE_PUSH_DELAY_HOURS = 3


@dataclass(frozen=True, slots=True)
class DueCatalogListedInvitePush:
    trainer_id: int
    trainer_telegram_id: int


async def list_due_catalog_listed_invite_pushes(session: AsyncSession) -> list[DueCatalogListedInvitePush]:
    result = await session.execute(
        text(
            """
            SELECT t.id, t.telegram_id
            FROM trainers t
            JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE t.catalog_state = :published
              AND t.status != :deactivated
              AND t.telegram_id IS NOT NULL
              AND tp.catalog_listed_invite_push_sent_at IS NULL
              AND t.catalog_state_changed_at IS NOT NULL
              AND t.catalog_state_changed_at <= NOW() - make_interval(hours => :delay_hours)
              AND NOT EXISTS (
                SELECT 1 FROM bookings b
                WHERE b.trainer_id = t.id
                  AND NOT b.is_sandbox
                  AND b.status IN ('confirmed', 'completed')
              )
            ORDER BY t.catalog_state_changed_at ASC
            LIMIT 50
            """
        ),
        {
            "published": CATALOG_STATE_PUBLISHED,
            "deactivated": TRAINER_STATUS_DEACTIVATED,
            "delay_hours": CATALOG_LISTED_INVITE_PUSH_DELAY_HOURS,
        },
    )
    out: list[DueCatalogListedInvitePush] = []
    for row in result.fetchall():
        out.append(DueCatalogListedInvitePush(trainer_id=int(row[0]), trainer_telegram_id=int(row[1])))
    return out


async def mark_catalog_listed_invite_push_sent(session: AsyncSession, trainer_id: int) -> bool:
    """Set sent timestamp once; returns False if already set (race)."""
    r = await session.execute(
        text(
            """
            UPDATE trainer_profiles
            SET catalog_listed_invite_push_sent_at = NOW()
            WHERE trainer_id = :tid
              AND catalog_listed_invite_push_sent_at IS NULL
            RETURNING trainer_id
            """
        ),
        {"tid": int(trainer_id)},
    )
    if r.fetchone() is None:
        return False
    await session.commit()
    return True
