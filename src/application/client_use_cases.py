"""
Client entity: get-or-create by telegram_id or by phone (trainer-added, no bot yet).
Single source of identity for bookings and requests.
"""
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_phone(phone: str | None) -> str | None:
    """Digits only; empty string becomes None. Used for unique lookup."""
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone.strip())
    return digits if digits else None


async def get_or_create_client(
    session: AsyncSession,
    telegram_id: int,
    *,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    telegram_username: str | None = None,
) -> int:
    """
    Resolve client by telegram_id (natural key). Create if missing; optionally update name/phone.
    Returns client_id. Caller must commit (we do not commit here to allow same transaction as booking/request).
    """
    r = await session.execute(
        text("SELECT id, phone, first_name, last_name, telegram_username FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if row:
        client_id = row[0]
        # Optional update: fill or refresh name/phone when provided
        updates = []
        params: dict = {"cid": client_id}
        if phone is not None and (phone_val := (phone or "").strip()[:32]):
            updates.append("phone = :phone")
            params["phone"] = phone_val
            norm = normalize_phone(phone_val)
            if norm is not None:
                updates.append("phone_normalized = :phone_normalized")
                params["phone_normalized"] = norm
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = (first_name or "").strip()[:64] or None
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = (last_name or "").strip()[:64] or None
        if telegram_username is not None:
            updates.append("telegram_username = :telegram_username")
            params["telegram_username"] = (telegram_username or "").strip()[:64] or None
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id
    # Insert new client (with phone_normalized if phone provided)
    phone_val = (phone or "").strip()[:32] or None
    phone_norm = normalize_phone(phone_val) if phone_val else None
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, telegram_username, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, :tuname, :first_name, :last_name, :phone, :phone_normalized)
            RETURNING id
        """),
        {
            "tid": telegram_id,
            "tuname": (telegram_username or "").strip()[:64] or None,
            "first_name": (first_name or "").strip()[:64] or None,
            "last_name": (last_name or "").strip()[:64] or None,
            "phone": phone_val,
            "phone_normalized": phone_norm,
        },
    )
    (client_id,) = r.fetchone()
    return client_id


async def apply_certificate_recipient_to_client(
    session: AsyncSession,
    client_id: int,
    recipient_name: str | None,
    recipient_phone: str | None,
) -> None:
    """
    When client opens welcome link, fill their profile from certificate if empty.
    recipient_name: split on first space → first_name, last_name; if no space, all in first_name.
    recipient_phone: set phone (and phone_normalized) only if client.phone is empty.
    Only updates fields that are currently empty; does not overwrite existing data.
    """
    r = await session.execute(
        text("SELECT first_name, last_name, phone FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return
    first_name, last_name, phone = row[0], row[1], row[2]
    updates = []
    params: dict = {"cid": client_id}
    if recipient_name and (recipient_name := recipient_name.strip()):
        parts = recipient_name.split(maxsplit=1)
        if not (first_name and first_name.strip()):
            updates.append("first_name = :first_name")
            params["first_name"] = (parts[0] or "").strip()[:64] or None
        if not (last_name and last_name.strip()) and len(parts) > 1:
            updates.append("last_name = :last_name")
            params["last_name"] = (parts[1] or "").strip()[:64] or None
        elif not (last_name and last_name.strip()) and len(parts) == 1:
            pass  # only first_name set above
    if recipient_phone and (recipient_phone := recipient_phone.strip()[:32]) and not (phone and phone.strip()):
        updates.append("phone = :phone")
        params["phone"] = recipient_phone
        norm = normalize_phone(recipient_phone)
        if norm:
            updates.append("phone_normalized = :phone_normalized")
            params["phone_normalized"] = norm
    if updates:
        await session.execute(
            text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
            params,
        )


async def get_or_create_client_by_phone(
    session: AsyncSession,
    phone: str,
    first_name: str | None = None,
    last_name: str | None = None,
) -> int:
    """
    Resolve client by normalized phone (trainer-added, no telegram_id).
    If found: optionally update first_name/last_name; return client_id.
    If not found: create with telegram_id=NULL, phone, phone_normalized, names; return client_id.
    Caller must commit.
    """
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        raise ValueError("Phone required (digits)")
    first_name = (first_name or "").strip()[:64] or None
    last_name = (last_name or "").strip()[:64] or None
    r = await session.execute(
        text("""
            SELECT id, first_name, last_name FROM clients
            WHERE phone_normalized = :pn
        """),
        {"pn": phone_norm},
    )
    row = r.fetchone()
    if row:
        client_id = row[0]
        updates = []
        params: dict = {"cid": client_id}
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = first_name
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = last_name
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id
    # Create: store display phone (original) and normalized for lookup
    phone_display = (phone or "").strip()[:32] or phone_norm[:32]
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized)
            VALUES (NULL, :first_name, :last_name, :phone, :phone_normalized)
            RETURNING id
        """),
        {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone_display,
            "phone_normalized": phone_norm,
        },
    )
    (client_id,) = r.fetchone()
    return client_id


async def get_client_by_phone(session: AsyncSession, phone: str) -> dict | None:
    """Find client by normalized phone. Returns id, telegram_id, first_name, last_name, phone or None."""
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        return None
    r = await session.execute(
        text("""
            SELECT id, telegram_id, first_name, last_name, phone
            FROM clients WHERE phone_normalized = :pn
        """),
        {"pn": phone_norm},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "telegram_id": row[1],
        "first_name": row[2] or "",
        "last_name": row[3] or "",
        "phone": (row[4] or "").strip(),
    }


async def attach_telegram_id_to_client(
    session: AsyncSession,
    client_id: int,
    telegram_id: int,
) -> bool:
    """Attach telegram_id to client (e.g. after phone verification). Returns True if updated."""
    r = await session.execute(
        text("""
            UPDATE clients SET telegram_id = :tid, updated_at = now()
            WHERE id = :cid AND telegram_id IS NULL
            RETURNING id
        """),
        {"tid": telegram_id, "cid": client_id},
    )
    return r.fetchone() is not None


async def get_client_id_by_telegram_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Return client_id for telegram_id, or None if not found."""
    r = await session.execute(
        text("SELECT id FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_client_telegram_id(session: AsyncSession, client_id: int) -> int | None:
    """Return telegram_id for client_id, or None if not linked (trainer-added client without Telegram)."""
    r = await session.execute(
        text("SELECT telegram_id FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def get_client_profile_basic(
    session: AsyncSession,
    telegram_id: int,
) -> dict | None:
    """
    Basic client profile for flows: id + first/last name + phone (if any) by telegram_id.
    Used to decide whether to ask for name/phone again in booking/request flows.
    """
    r = await session.execute(
        text("SELECT id, first_name, last_name, phone FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "first_name": row[1] or "",
        "last_name": row[2] or "",
        "phone": (row[3] or "").strip(),
    }
