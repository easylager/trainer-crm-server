"""
Trainer–Telegram binding: consume one-time link token and resolve trainer by telegram_id.
All DB access via raw SQL.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.miniapp_auth.types import MiniAppPlatform, MiniAppPrincipal
from src.infrastructure.db.models import TRAINER_STATUS_PENDING_PROFILE
from src.shared.trainer_status import normalize_trainer_status_value


@dataclass(frozen=True, slots=True)
class ConsumeLinkTokenResult:
    """Outcome of consume_link_token: either linked trainer_id or a failure reason."""

    trainer_id: int | None = None
    error: Literal["invalid_token", "telegram_other_trainer"] | None = None
    first_login: bool = False  # True if this is the first time trainer links Telegram


async def consume_link_token(
    session: AsyncSession,
    token: str,
    telegram_id: int,
    *,
    telegram_username: str | None = None,
) -> ConsumeLinkTokenResult:
    """
    Find valid token, bind Telegram to trainer, mark token used.

    Landing tokens may have trainer_id=NULL — trainer row is created on first open.
    If Telegram is already linked, consumes the token and returns the existing trainer (repeat CTA).
    """
    now = datetime.now(timezone.utc)
    r = await session.execute(
        text("""
            SELECT trainer_id FROM trainer_link_tokens
            WHERE token = :token AND used_at IS NULL AND expires_at > :now
        """),
        {"token": token, "now": now},
    )
    row = r.fetchone()
    if not row:
        return ConsumeLinkTokenResult(error="invalid_token")
    token_trainer_id = row[0]
    username_val = (telegram_username or "").strip()[:64] or None

    r_existing = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid LIMIT 1"),
        {"tid": telegram_id},
    )
    existing = r_existing.scalar()
    if existing is not None:
        existing_id = int(existing)
        if token_trainer_id is None or existing_id == int(token_trainer_id):
            await session.execute(
                text("UPDATE trainers SET telegram_username = :tuname WHERE id = :id"),
                {"tuname": username_val, "id": existing_id},
            )
            await session.execute(
                text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
                {"now": now, "token": token},
            )
            await session.commit()
            return ConsumeLinkTokenResult(trainer_id=existing_id, first_login=False)
        await session.rollback()
        return ConsumeLinkTokenResult(error="telegram_other_trainer")

    if token_trainer_id is None:
        try:
            created = await session.execute(
                text(
                    """
                    INSERT INTO trainers (status, telegram_id, telegram_username, created_at)
                    VALUES (:st, :tid, :tuname, :now)
                    RETURNING id
                    """
                ),
                {
                    "st": TRAINER_STATUS_PENDING_PROFILE,
                    "tid": telegram_id,
                    "tuname": username_val,
                    "now": now,
                },
            )
            new_row = created.fetchone()
            if new_row is None:
                await session.rollback()
                return ConsumeLinkTokenResult(error="invalid_token")
            trainer_id = int(new_row[0])
            await session.execute(
                text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
                {"now": now, "token": token},
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            retry = await session.execute(
                text("SELECT id FROM trainers WHERE telegram_id = :tid LIMIT 1"),
                {"tid": telegram_id},
            )
            retry_id = retry.scalar()
            if retry_id is not None:
                await session.execute(
                    text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
                    {"now": now, "token": token},
                )
                await session.commit()
                return ConsumeLinkTokenResult(trainer_id=int(retry_id), first_login=True)
            return ConsumeLinkTokenResult(error="telegram_other_trainer")
        return ConsumeLinkTokenResult(trainer_id=trainer_id, first_login=True)

    trainer_id = int(token_trainer_id)
    try:
        await session.execute(
            text("UPDATE trainers SET telegram_id = :tid, telegram_username = :tuname WHERE id = :id"),
            {"tid": telegram_id, "tuname": username_val, "id": trainer_id},
        )
        await session.execute(
            text("UPDATE trainer_link_tokens SET used_at = :now WHERE token = :token"),
            {"now": now, "token": token},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return ConsumeLinkTokenResult(error="telegram_other_trainer")
    return ConsumeLinkTokenResult(trainer_id=trainer_id, first_login=True)


async def get_trainer_row_by_telegram_id(session: AsyncSession, telegram_id: int) -> dict | None:
    """Linked trainer row (any status). Used for onboarding / gate before active."""
    r = await session.execute(
        text(
            """
            SELECT id, status, moderation_feedback
            FROM trainers
            WHERE telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "status": normalize_trainer_status_value(row[1]),
        "moderation_feedback": row[2],
    }


async def get_trainer_row_by_vk_user_id(session: AsyncSession, vk_user_id: int) -> dict | None:
    """Linked trainer row by VK id (any status)."""
    r = await session.execute(
        text(
            """
            SELECT id, status, moderation_feedback
            FROM trainers
            WHERE vk_user_id = :vk
            LIMIT 1
            """
        ),
        {"vk": vk_user_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "status": normalize_trainer_status_value(row[1]),
        "moderation_feedback": row[2],
    }


async def get_trainer_row_for_miniapp_principal(
    session: AsyncSession,
    principal: MiniAppPrincipal,
) -> dict | None:
    """Resolve lightweight trainer row from Telegram or MAX Mini App principal."""
    if principal.platform == MiniAppPlatform.TELEGRAM:
        return await get_trainer_row_by_telegram_id(session, principal.user_id)
    if principal.platform == MiniAppPlatform.MAX:
        return await get_trainer_row_by_vk_user_id(session, principal.user_id)
    return None


async def get_trainer_by_telegram_id(session: AsyncSession, telegram_id: int) -> bool:
    """True if this telegram_id is linked to an active trainer (bot access allowed)."""
    r = await session.execute(
        text("SELECT 1 FROM trainers WHERE telegram_id = :tid AND status = 'active' LIMIT 1"),
        {"tid": telegram_id},
    )
    return r.fetchone() is not None


async def get_trainer_id_by_telegram_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Return trainer id if linked and status=active (bot access allowed), else None."""
    r = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid AND status = 'active' LIMIT 1"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_trainer_id_linked_any_status(session: AsyncSession, telegram_id: int) -> int | None:
    """Trainer id for linked Telegram user regardless of status (onboarding Mini App, etc.)."""
    r = await session.execute(
        text("SELECT id FROM trainers WHERE telegram_id = :tid LIMIT 1"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_trainer_id_for_webapp_trainer_operations(session: AsyncSession, telegram_id: int) -> int | None:
    """
    Trainer Mini App operations: schedule, slots, trainer-side bookings, clients, notes.

    Onboarding v2: any linked trainer who is not ``deactivated`` may run their own operations from
    the first second. Profile completeness and catalog moderation no longer gate this — moderation
    only decides whether the public catalog lists the trainer.

    Payments, catalog products, and other catalog-facing surfaces still use
    ``get_trainer_id_by_telegram_id`` (active only).
    """
    from src.infrastructure.db.models import TRAINER_STATUS_DEACTIVATED

    row = await get_trainer_row_by_telegram_id(session, telegram_id)
    if not row:
        return None
    if (row.get("status") or "").strip().lower() == TRAINER_STATUS_DEACTIVATED:
        return None
    return int(row["id"])


async def get_trainer_id_by_telegram_id_from_principal(
    session: AsyncSession,
    principal: MiniAppPrincipal,
) -> int | None:
    """Active trainer id for Mini App principal (Telegram or MAX)."""
    row = await get_trainer_row_for_miniapp_principal(session, principal)
    if not row:
        return None
    st = (row.get("status") or "").strip().lower()
    if st != "active":
        return None
    return int(row["id"])


async def get_trainer_id_linked_any_status_from_principal(
    session: AsyncSession,
    principal: MiniAppPrincipal,
) -> int | None:
    row = await get_trainer_row_for_miniapp_principal(session, principal)
    return int(row["id"]) if row else None


async def get_trainer_id_for_webapp_trainer_operations_from_principal(
    session: AsyncSession,
    principal: MiniAppPrincipal,
) -> int | None:
    """Same rule as :func:`get_trainer_id_for_webapp_trainer_operations`, for a Mini App principal."""
    from src.infrastructure.db.models import TRAINER_STATUS_DEACTIVATED

    row = await get_trainer_row_for_miniapp_principal(session, principal)
    if not row:
        return None
    if (row.get("status") or "").strip().lower() == TRAINER_STATUS_DEACTIVATED:
        return None
    return int(row["id"])


async def list_linked_trainer_telegram_ids_for_hub_menu(session: AsyncSession) -> list[int]:
    """Telegram chat ids for trainers who should have the per-chat «Обзор» hub menu button."""
    from src.infrastructure.db.models import TRAINER_STATUS_DEACTIVATED

    r = await session.execute(
        text(
            """
            SELECT telegram_id
            FROM trainers
            WHERE telegram_id IS NOT NULL
              AND lower(trim(status)) != :deactivated
            ORDER BY id
            """
        ),
        {"deactivated": TRAINER_STATUS_DEACTIVATED},
    )
    return [int(row[0]) for row in r.fetchall()]
