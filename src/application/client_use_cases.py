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
    vk_user_id: int | None = None,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    telegram_username: str | None = None,
) -> int:
    """
    Resolve client by telegram_id (surrogate for MAX catalog) or vk_user_id. Create if missing; optionally update name/phone.
    If telegram row is missing but phone matches an offline row (telegram_id IS NULL), bind Telegram to it.
    Returns client_id. Caller must commit (we do not commit here to allow same transaction as booking/request).
    """
    phone_val = (phone or "").strip()[:32] if phone is not None else None
    if phone_val == "":
        phone_val = None
    phone_norm = normalize_phone(phone_val) if phone_val else None
    first_name_val = (first_name or "").strip()[:64] or None
    last_name_val = (last_name or "").strip()[:64] or None
    telegram_username_val = (telegram_username or "").strip()[:64] or None

    r = await session.execute(
        text("SELECT id, phone, first_name, last_name, telegram_username FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row and vk_user_id is not None:
        r = await session.execute(
            text("SELECT id, phone, first_name, last_name, telegram_username FROM clients WHERE vk_user_id = :vk"),
            {"vk": vk_user_id},
        )
        row = r.fetchone()
    if row:
        client_id = row[0]
        # Optional update: fill or refresh name/phone when provided
        updates = []
        params: dict = {"cid": client_id}
        if phone is not None and phone_val is not None:
            updates.append("phone = :phone")
            params["phone"] = phone_val
            if phone_norm is not None:
                updates.append("phone_normalized = :phone_normalized")
                params["phone_normalized"] = phone_norm
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = first_name_val
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = last_name_val
        if telegram_username is not None:
            updates.append("telegram_username = :telegram_username")
            params["telegram_username"] = telegram_username_val
        if vk_user_id is not None:
            updates.append("vk_user_id = COALESCE(vk_user_id, :vk)")
            params["vk"] = vk_user_id
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id

    if phone_norm is not None:
        # Merge path: trainer-created offline client enters Mini App via public link.
        # Attach telegram_id to the existing phone row to keep bookings/history in one profile.
        r_phone = await session.execute(
            text(
                """
                SELECT id, telegram_id
                FROM clients
                WHERE phone_normalized = :pn
                ORDER BY CASE WHEN telegram_id IS NULL THEN 0 ELSE 1 END, id
                LIMIT 1
                """
            ),
            {"pn": phone_norm},
        )
        row_phone = r_phone.fetchone()
        if row_phone and (row_phone[1] is None or int(row_phone[1]) == int(telegram_id)):
            client_id = int(row_phone[0])
            updates = ["telegram_id = :tid"]
            params = {"cid": client_id, "tid": telegram_id}
            if vk_user_id is not None:
                updates.append("vk_user_id = :vk")
                params["vk"] = vk_user_id
            if phone is not None and phone_val is not None:
                updates.append("phone = :phone")
                params["phone"] = phone_val
                updates.append("phone_normalized = :phone_normalized")
                params["phone_normalized"] = phone_norm
            if first_name is not None:
                updates.append("first_name = :first_name")
                params["first_name"] = first_name_val
            if last_name is not None:
                updates.append("last_name = :last_name")
                params["last_name"] = last_name_val
            if telegram_username is not None:
                updates.append("telegram_username = :telegram_username")
                params["telegram_username"] = telegram_username_val
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
            return client_id

    # Insert new client (with phone_normalized if phone provided)
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, vk_user_id, telegram_username, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, :vk, :tuname, :first_name, :last_name, :phone, :phone_normalized)
            RETURNING id
        """),
        {
            "tid": telegram_id,
            "vk": vk_user_id,
            "tuname": telegram_username_val,
            "first_name": first_name_val,
            "last_name": last_name_val,
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


async def get_client_phone_for_webapp(session: AsyncSession, telegram_id: int) -> str | None:
    """
    Phone for Mini App prefill: row linked to telegram_id, or sibling row with same phone_normalized
    (trainer-added duplicate before merge).
    """
    r = await session.execute(
        text("""
            SELECT COALESCE(
                NULLIF(TRIM(COALESCE(c.phone, '')), ''),
                (SELECT TRIM(COALESCE(o.phone, '')) FROM clients o
                 WHERE o.phone_normalized IS NOT NULL
                   AND c.phone_normalized IS NOT NULL
                   AND o.phone_normalized = c.phone_normalized
                   AND o.id IS DISTINCT FROM c.id
                   AND TRIM(COALESCE(o.phone, '')) <> ''
                 LIMIT 1)
            ) AS phone
            FROM clients c
            WHERE c.telegram_id = :tid
            LIMIT 1
        """),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    out = str(row[0]).strip()
    return out or None
