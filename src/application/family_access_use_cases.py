"""
Family access: one primary ``clients`` row (child profile + primary phone); additional Telegram users
see the same bookings/passes via ``client_family_access_members``.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_dossier_use_cases import sync_family_access_dossier_tags
from src.application.client_use_cases import (
    get_client_id_by_telegram_id,
    get_family_primary_client_id_for_telegram,
)
from src.application.trainer_client_scope import list_trainer_ids_for_client_crm_scope
from src.application.welcome_link_use_cases import WELCOME_TOKEN_TYPE_FAMILY_ACCESS, create_welcome_link_token
from src.infrastructure.repositories.client_session_repository import ClientSessionRepository
from src.shared.config import Settings

MAX_FAMILY_ACCESS_EXTRA_MEMBERS = 2


async def count_family_extra_members(session: AsyncSession, primary_client_id: int) -> int:
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM client_family_access_members
            WHERE primary_client_id = :cid
            """
        ),
        {"cid": int(primary_client_id)},
    )
    row = r.fetchone()
    return int(row[0] or 0) if row else 0


async def is_primary_family_owner(
    session: AsyncSession, *, primary_client_id: int, telegram_id: int
) -> bool:
    """True if ``telegram_id`` is the primary row's owner (``clients.telegram_id`` for this client id)."""
    r = await session.execute(
        text(
            """
            SELECT 1 FROM clients
            WHERE id = :cid AND telegram_id = :tid
            LIMIT 1
            """
        ),
        {"cid": int(primary_client_id), "tid": int(telegram_id)},
    )
    return r.fetchone() is not None


async def list_family_access_telegram_ids_for_reminders(session: AsyncSession, primary_client_id: int) -> list[int]:
    """All Telegram chat ids that should receive booking reminders for this client row."""
    from src.application.client_use_cases import get_client_telegram_id

    out: list[int] = []
    own_or_account = await get_client_telegram_id(session, int(primary_client_id))
    if own_or_account is not None:
        out.append(int(own_or_account))
    r2 = await session.execute(
        text(
            """
            SELECT member_telegram_id FROM client_family_access_members
            WHERE primary_client_id = :cid
            ORDER BY id ASC
            """
        ),
        {"cid": int(primary_client_id)},
    )
    for t in r2.fetchall():
        if t[0] is not None:
            tid = int(t[0])
            if tid not in out:
                out.append(tid)
    return out


async def _pick_trainer_id_for_family_token(session: AsyncSession, primary_client_id: int) -> int | None:
    """Trainer for welcome token: same scope as ``trainer_has_access_to_client`` (roster, then latest booking, then group)."""
    ids = await list_trainer_ids_for_client_crm_scope(session, int(primary_client_id))
    return ids[0] if ids else None


async def create_family_access_invite_token(
    session: AsyncSession,
    *,
    primary_client_id: int,
    inviter_telegram_id: int,
) -> tuple[str | None, str | None]:
    """
    One-time welcome link for an extra family Telegram user.
    Returns (deeplink_url, error_code) where error_code is owner_only | roster_required | limit_reached | no_bot.
    """
    if not await is_primary_family_owner(
        session, primary_client_id=int(primary_client_id), telegram_id=int(inviter_telegram_id)
    ):
        return None, "owner_only"
    n = await count_family_extra_members(session, primary_client_id)
    if n >= MAX_FAMILY_ACCESS_EXTRA_MEMBERS:
        return None, "limit_reached"
    trainer_id = await _pick_trainer_id_for_family_token(session, primary_client_id)
    if trainer_id is None:
        return None, "roster_required"
    settings = Settings()
    uname = (settings.client_bot_username or "").strip().lstrip("@")
    if not uname:
        return None, "no_bot"
    token = await create_welcome_link_token(
        session,
        WELCOME_TOKEN_TYPE_FAMILY_ACCESS,
        trainer_id,
        client_id=int(primary_client_id),
    )
    url = f"https://t.me/{uname}?start=welcome_t_{token}"
    return url, None


async def _clone_client_trainer_edges(session: AsyncSession, owner_tid: int, member_tid: int) -> None:
    await session.execute(
        text(
            """
            INSERT INTO client_trainer_edges (
                telegram_id, trainer_id,
                is_saved, is_primary, notify_when_slots, completed_count,
                saved_at, notify_when_slots_at,
                last_booking_at, last_completed_at, last_interaction_at,
                last_booking_service_id, saved_catalog_service_id,
                context_type, context_id
            )
            SELECT
                :mtid, trainer_id,
                is_saved, is_primary, notify_when_slots, completed_count,
                saved_at, notify_when_slots_at,
                last_booking_at, last_completed_at, last_interaction_at,
                last_booking_service_id, saved_catalog_service_id,
                context_type, context_id
            FROM client_trainer_edges
            WHERE telegram_id = :otid
            ON CONFLICT (telegram_id, trainer_id) DO NOTHING
            """
        ),
        {"otid": int(owner_tid), "mtid": int(member_tid)},
    )


async def _clone_client_session_row(session: AsyncSession, owner_tid: int, member_tid: int) -> None:
    repo_o = ClientSessionRepository(session)
    row = await repo_o.get(owner_tid)
    if not row:
        return
    repo_m = ClientSessionRepository(session)
    existing = await repo_m.get(member_tid)
    if existing:
        return
    payload = row.get("payload")
    await repo_m.upsert(
        member_tid,
        state=str(row.get("state") or "idle"),
        city_id=row.get("city_id"),
        selected_service_id=row.get("selected_service_id"),
        selected_trainer_id=row.get("selected_trainer_id"),
        selected_arena_id=row.get("selected_arena_id"),
        payload=payload if isinstance(payload, dict) else None,
    )


async def attach_family_member_from_invite(
    session: AsyncSession,
    *,
    primary_client_id: int,
    member_telegram_id: int,
    invited_by_telegram_id: int | None,
    telegram_username: str | None,
) -> tuple[bool, str | None, bool]:
    """
    Insert family member row + clone edges/session from owner.
    Returns (ok, error, is_new_member): error in duplicate_client | limit_reached | no_owner_telegram;
    is_new_member False when already linked (idempotent).
    """
    pid = int(primary_client_id)
    mtid = int(member_telegram_id)
    existing_client = await get_client_id_by_telegram_id(session, mtid)
    if existing_client is not None and int(existing_client) != pid:
        return False, "duplicate_client", False

    r_own = await session.execute(
        text("SELECT telegram_id FROM clients WHERE id = :cid LIMIT 1"),
        {"cid": pid},
    )
    row_own = r_own.fetchone()
    owner_tid = int(row_own[0]) if row_own and row_own[0] is not None else None
    if owner_tid is not None and int(owner_tid) == mtid:
        return True, None, False

    fam_existing = await get_family_primary_client_id_for_telegram(session, mtid)
    if fam_existing is not None and int(fam_existing) == pid:
        return True, None, False
    if fam_existing is not None:
        return False, "duplicate_client", False
    n = await count_family_extra_members(session, pid)
    if n >= MAX_FAMILY_ACCESS_EXTRA_MEMBERS:
        return False, "limit_reached", False
    if owner_tid is None:
        return False, "no_owner_telegram", False
    un = (telegram_username or "").strip().lstrip("@")[:64] or None
    if un == "":
        un = None
    await session.execute(
        text(
            """
            INSERT INTO client_family_access_members (
                primary_client_id, member_telegram_id, telegram_username, invited_by_telegram_id
            )
            VALUES (:pid, :mtid, :un, :inv)
            """
        ),
        {"pid": pid, "mtid": mtid, "un": un, "inv": invited_by_telegram_id},
    )
    # Edges FK client_sessions.telegram_id — parent row must exist first.
    await _clone_client_session_row(session, owner_tid, mtid)
    await _clone_client_trainer_edges(session, owner_tid, mtid)
    await sync_family_access_dossier_tags(session, pid)
    return True, None, True


async def revoke_family_member(
    session: AsyncSession,
    *,
    primary_client_id: int,
    owner_telegram_id: int,
    member_telegram_id: int,
) -> bool:
    if not await is_primary_family_owner(
        session, primary_client_id=int(primary_client_id), telegram_id=int(owner_telegram_id)
    ):
        return False
    r = await session.execute(
        text(
            """
            DELETE FROM client_family_access_members
            WHERE primary_client_id = :pid AND member_telegram_id = :mtid
            RETURNING id
            """
        ),
        {"pid": int(primary_client_id), "mtid": int(member_telegram_id)},
    )
    if r.fetchone() is None:
        return False
    await session.execute(
        text("DELETE FROM client_trainer_edges WHERE telegram_id = :tid"),
        {"tid": int(member_telegram_id)},
    )
    await session.execute(
        text("DELETE FROM client_sessions WHERE telegram_id = :tid"),
        {"tid": int(member_telegram_id)},
    )
    await sync_family_access_dossier_tags(session, int(primary_client_id))
    return True


async def list_family_access_members_api(
    session: AsyncSession,
    *,
    viewer_telegram_id: int,
) -> dict[str, Any] | None:
    """
    For Mini App: resolve viewer's primary client id, return owner + members with roles.
    None if viewer has no client id.
    """
    cid = await get_client_id_by_telegram_id(session, int(viewer_telegram_id))
    if cid is None:
        return None
    pid = int(cid)
    r_owner = await session.execute(
        text(
            """
            SELECT telegram_id, telegram_username, first_name, last_name
            FROM clients WHERE id = :cid LIMIT 1
            """
        ),
        {"cid": pid},
    )
    orow = r_owner.mappings().first()
    if not orow:
        return None
    owner_tid = orow.get("telegram_id")
    members: list[dict[str, Any]] = []
    if owner_tid is not None:
        fn = (orow.get("first_name") or "").strip()
        ln = (orow.get("last_name") or "").strip()
        label = f"{fn} {ln}".strip() or None
        members.append(
            {
                "telegram_id": int(owner_tid),
                "telegram_username": (orow.get("telegram_username") or "").strip() or None,
                "display_label": label,
                "role": "owner",
            }
        )
    r_m = await session.execute(
        text(
            """
            SELECT member_telegram_id, telegram_username
            FROM client_family_access_members
            WHERE primary_client_id = :cid
            ORDER BY id ASC
            """
        ),
        {"cid": pid},
    )
    for row in r_m.fetchall():
        tid, un = int(row[0]), (row[1] or "").strip() or None
        members.append(
            {
                "telegram_id": tid,
                "telegram_username": un,
                "display_label": (f"@{un}" if un else f"id:{tid}"),
                "role": "member",
            }
        )
    can_manage = await is_primary_family_owner(session, primary_client_id=pid, telegram_id=int(viewer_telegram_id))
    return {
        "primary_client_id": pid,
        "viewer_telegram_id": int(viewer_telegram_id),
        "max_extra_members": MAX_FAMILY_ACCESS_EXTRA_MEMBERS,
        "extra_members_count": await count_family_extra_members(session, pid),
        "can_manage": can_manage,
        "members": members,
    }
