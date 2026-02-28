"""
Client entity: get-or-create by telegram_id; optional name/phone updates.
Single source of identity for bookings and requests.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_or_create_client(
    session: AsyncSession,
    telegram_id: int,
    *,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> int:
    """
    Resolve client by telegram_id (natural key). Create if missing; optionally update name/phone.
    Returns client_id. Caller must commit (we do not commit here to allow same transaction as booking/request).
    """
    r = await session.execute(
        text("SELECT id, phone, first_name, last_name FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if row:
        client_id = row[0]
        # Optional update: fill or refresh name/phone when provided
        updates = []
        params: dict = {"cid": client_id}
        if phone is not None and (phone := (phone or "").strip()[:32]):
            updates.append("phone = :phone")
            params["phone"] = phone
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = (first_name or "").strip()[:64] or None
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = (last_name or "").strip()[:64] or None
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id
    # Insert new client
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, first_name, last_name, phone)
            VALUES (:tid, :first_name, :last_name, :phone)
            RETURNING id
        """),
        {
            "tid": telegram_id,
            "first_name": (first_name or "").strip()[:64] or None,
            "last_name": (last_name or "").strip()[:64] or None,
            "phone": (phone or "").strip()[:32] or None,
        },
    )
    (client_id,) = r.fetchone()
    return client_id


async def get_client_id_by_telegram_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Return client_id for telegram_id, or None if not found."""
    r = await session.execute(
        text("SELECT id FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None
