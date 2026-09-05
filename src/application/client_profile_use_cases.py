"""
Client profile links: one Telegram/VK account acting as several client profiles (self + children).

Decouples "who is logged in" (``account_telegram_id``) from "who the service is for"
(``profile_client_id``, a ``clients`` row). See .ai/DECISION-multi-profile-clients.md and
.ai/EPIC1-client-multi-profile.md for the full domain writeup.

Orthogonal to ``client_family_access_members`` (several accounts sharing one profile) —
that mechanism is untouched; ``list_accessible_profiles`` surfaces its result alongside
``client_profile_links`` rows so both are visible in one switcher, without merging the tables.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_use_cases import (
    get_client_id_by_telegram_id,
    get_family_primary_client_id_for_telegram,
)
from src.infrastructure.db.models import CLIENT_PROFILE_ROLE_GUARDIAN, CLIENT_PROFILE_ROLE_SELF

MAX_GUARDIAN_PROFILES_PER_ACCOUNT = 6


def sql_client_notify_telegram_id(alias: str = "c") -> str:
    """
    SQL expression: client's own telegram_id, else the account that owns a profile link.

    Guardian/child rows have ``telegram_id IS NULL`` — pushes and trainer «Написать» must
    reach the parent account's chat via ``client_profile_links.account_telegram_id``.
    """
    return (
        f"COALESCE("
        f"{alias}.telegram_id, "
        f"(SELECT l.account_telegram_id FROM client_profile_links l "
        f"WHERE l.profile_client_id = {alias}.id "
        f"ORDER BY CASE l.role WHEN 'self' THEN 0 ELSE 1 END, l.id LIMIT 1))"
    )


def sql_client_notify_phone(alias: str = "c") -> str:
    """Own phone, else the account self-row phone (guardian child has no phone of their own)."""
    return (
        f"COALESCE("
        f"NULLIF(TRIM({alias}.phone), ''), "
        f"(SELECT NULLIF(TRIM(p.phone), '') FROM clients p "
        f"WHERE p.telegram_id = {sql_client_notify_telegram_id(alias)} LIMIT 1))"
    )


def sql_client_booked_for_name(alias: str = "c") -> str:
    """Child/guardian first name for client-push copy; NULL for self rows."""
    return (
        f"CASE WHEN {alias}.telegram_id IS NULL "
        f"THEN NULLIF(TRIM({alias}.first_name), '') ELSE NULL END"
    )


async def get_account_telegram_id_for_profile(
    session: AsyncSession, profile_client_id: int
) -> int | None:
    """Account Telegram id linked to this profile, if any (self or guardian)."""
    r = await session.execute(
        text(
            """
            SELECT account_telegram_id
            FROM client_profile_links
            WHERE profile_client_id = :cid
            ORDER BY CASE role WHEN 'self' THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        ),
        {"cid": int(profile_client_id)},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def resolve_client_notify_contact(
    session: AsyncSession,
    *,
    client_id: int,
    telegram_id: int | None,
    phone: str | None,
) -> dict[str, Any]:
    """
    Trainer-facing / push contact for a booking's ``client_id`` row.

    Keeps the profile's own identity (name lives on the caller). When the row has no
    Telegram (guardian child), resolves the parent account chat and, if needed, the
    account self-row phone for contact display.
    """
    own_tid = int(telegram_id) if telegram_id is not None else None
    own_phone = (phone or "").strip()
    if own_tid is not None:
        return {
            "client_telegram_id": own_tid,
            "client_phone": own_phone,
            "booked_via_guardian": False,
        }

    account_tid = await get_account_telegram_id_for_profile(session, client_id)
    if account_tid is None:
        return {
            "client_telegram_id": None,
            "client_phone": own_phone,
            "booked_via_guardian": False,
        }

    contact_phone = own_phone
    if not contact_phone:
        r = await session.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(c.phone), ''), '')
                FROM clients c
                WHERE c.telegram_id = :tid
                LIMIT 1
                """
            ),
            {"tid": account_tid},
        )
        row = r.fetchone()
        contact_phone = (row[0] or "").strip() if row else ""

    return {
        "client_telegram_id": account_tid,
        "client_phone": contact_phone,
        "booked_via_guardian": True,
    }


async def _ensure_self_link(session: AsyncSession, account_telegram_id: int, client_id: int) -> None:
    """
    Lazily back-fill the ``self`` link for accounts created after the Slice 1 migration,
    or any row the one-off backfill missed. Idempotent; safe to call on every resolution.

    ``is_default`` is computed, not hardcoded ``true``: this can run *after* a guardian
    profile already exists and was made default (e.g. a legacy client row that never had
    a link until its first read post-guardian-creation) — hardcoding true here would then
    plant a second ``is_default=true`` row and silently break "which profile opens by
    default". True only when the account has no default at all yet.
    """
    await session.execute(
        text(
            """
            INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
            SELECT :tid, :cid, :role, NOT EXISTS (
                SELECT 1 FROM client_profile_links WHERE account_telegram_id = :tid AND is_default
            )
            ON CONFLICT (account_telegram_id, profile_client_id) DO NOTHING
            """
        ),
        {"tid": account_telegram_id, "cid": client_id, "role": CLIENT_PROFILE_ROLE_SELF},
    )


async def _is_own_row(session: AsyncSession, account_telegram_id: int, client_id: int) -> bool:
    r = await session.execute(
        text("SELECT 1 FROM clients WHERE id = :cid AND telegram_id = :tid LIMIT 1"),
        {"cid": client_id, "tid": account_telegram_id},
    )
    return r.fetchone() is not None


async def resolve_acting_client_id(
    session: AsyncSession,
    account_telegram_id: int,
    requested_profile_id: int | None = None,
) -> int | None:
    """
    Resolve which ``clients.id`` this request acts on behalf of.

    Without ``requested_profile_id`` this is byte-for-byte the legacy resolution
    (``get_client_id_by_telegram_id``) — every caller not yet passing a profile keeps
    today's behavior exactly, including the family-access fallback. When the account's
    own row is used, the ``self`` link is lazily ensured so it shows up in
    ``list_accessible_profiles`` going forward.

    With ``requested_profile_id``, access is checked against ``client_profile_links``
    (or against the family-access primary, for that untouched mechanism); an
    unauthorized or unknown profile falls back to the legacy resolution rather than
    raising, so a stale/foreign id in a client-sent header never blocks the request.
    """
    legacy_id = await get_client_id_by_telegram_id(session, account_telegram_id)
    if legacy_id is not None and await _is_own_row(session, account_telegram_id, legacy_id):
        await _ensure_self_link(session, account_telegram_id, legacy_id)

    if requested_profile_id is None:
        return legacy_id

    rpid = int(requested_profile_id)
    r = await session.execute(
        text(
            """
            SELECT 1 FROM client_profile_links
            WHERE account_telegram_id = :tid AND profile_client_id = :cid
            LIMIT 1
            """
        ),
        {"tid": account_telegram_id, "cid": rpid},
    )
    if r.fetchone() is not None:
        return rpid

    return legacy_id


async def list_accessible_profiles(
    session: AsyncSession, account_telegram_id: int
) -> list[dict[str, Any]]:
    """
    All profiles this account can act as: own ``client_profile_links`` rows, plus (read-only,
    for display parity) the family-shared profile from ``client_family_access_members`` if any.
    """
    legacy_id = await get_client_id_by_telegram_id(session, account_telegram_id)
    if legacy_id is not None and await _is_own_row(session, account_telegram_id, legacy_id):
        await _ensure_self_link(session, account_telegram_id, legacy_id)

    r = await session.execute(
        text(
            """
            SELECT l.profile_client_id, l.role, l.is_default,
                   c.first_name, c.last_name
            FROM client_profile_links l
            JOIN clients c ON c.id = l.profile_client_id
            WHERE l.account_telegram_id = :tid
            ORDER BY l.is_default DESC, (l.role = :self_role) DESC, l.id ASC
            """
        ),
        {"tid": account_telegram_id, "self_role": CLIENT_PROFILE_ROLE_SELF},
    )
    profiles = [
        {
            "client_id": int(row[0]),
            "role": row[1],
            "is_default": bool(row[2]),
            "first_name": row[3],
            "last_name": row[4],
        }
        for row in r.fetchall()
    ]
    linked_ids = {p["client_id"] for p in profiles}

    fam_cid = await get_family_primary_client_id_for_telegram(session, account_telegram_id)
    if fam_cid is not None and int(fam_cid) not in linked_ids:
        r_fam = await session.execute(
            text("SELECT first_name, last_name FROM clients WHERE id = :cid"),
            {"cid": int(fam_cid)},
        )
        row = r_fam.fetchone()
        if row is not None:
            profiles.append(
                {
                    "client_id": int(fam_cid),
                    "role": "family_access",
                    "is_default": len(profiles) == 0,
                    "first_name": row[0],
                    "last_name": row[1],
                }
            )
    return profiles


async def create_guardian_profile(
    session: AsyncSession,
    account_telegram_id: int,
    *,
    first_name: str,
    last_name: str | None = None,
    phone: str | None = None,
) -> int:
    """
    New independent profile (e.g. a second child): a fresh ``clients`` row with no
    Telegram identity of its own, linked to this account as ``guardian``.

    Caller must commit. Raises ValueError if the account already has
    ``MAX_GUARDIAN_PROFILES_PER_ACCOUNT`` guardian links (abuse/typo guard, not a
    product limit worth surfacing prominently — generous enough for any real family).
    """
    fn = (first_name or "").strip()[:64]
    if not fn:
        raise ValueError("first_name is required")
    ln = (last_name or "").strip()[:64] or None
    phone_val = (phone or "").strip()[:32] or None

    r_count = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM client_profile_links
            WHERE account_telegram_id = :tid AND role = :role
            """
        ),
        {"tid": account_telegram_id, "role": CLIENT_PROFILE_ROLE_GUARDIAN},
    )
    if int(r_count.scalar() or 0) >= MAX_GUARDIAN_PROFILES_PER_ACCOUNT:
        raise ValueError("guardian_profile_limit_reached")

    r_new = await session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name, phone, phone_normalized)
            VALUES (:fn, :ln, :phone, NULL)
            RETURNING id
            """
        ),
        {"fn": fn, "ln": ln, "phone": phone_val},
    )
    new_id = int(r_new.scalar())

    await session.execute(
        text(
            """
            INSERT INTO client_profile_links (account_telegram_id, profile_client_id, role, is_default)
            VALUES (:tid, :cid, :role, false)
            ON CONFLICT (account_telegram_id, profile_client_id) DO NOTHING
            """
        ),
        {"tid": account_telegram_id, "cid": new_id, "role": CLIENT_PROFILE_ROLE_GUARDIAN},
    )
    return new_id


async def set_default_profile(
    session: AsyncSession, account_telegram_id: int, profile_client_id: int
) -> bool:
    """Mark one of the account's accessible profiles as default. False if not accessible."""
    r = await session.execute(
        text(
            """
            SELECT 1 FROM client_profile_links
            WHERE account_telegram_id = :tid AND profile_client_id = :cid
            LIMIT 1
            """
        ),
        {"tid": account_telegram_id, "cid": profile_client_id},
    )
    if r.fetchone() is None:
        return False
    await session.execute(
        text(
            """
            UPDATE client_profile_links SET is_default = (profile_client_id = :cid)
            WHERE account_telegram_id = :tid
            """
        ),
        {"tid": account_telegram_id, "cid": profile_client_id},
    )
    return True
