"""
Pass products: trainer-defined subscription products (e.g. 5 sessions for 200 BYN).
List, create, update, delete. Used by trainer Mini App and (later) client purchase flow.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_pass_products(session: AsyncSession, trainer_id: int, active_only: bool = False) -> list[dict]:
    """List pass products for trainer with service name. Sorted by sort_order, id."""
    q = """
        SELECT p.id, p.trainer_id, p.name, p.sessions_total, p.price_cents, p.service_id, p.is_active, p.sort_order, p.created_at,
               COALESCE(s.name, '') AS service_name
        FROM trainer_pass_products p
        LEFT JOIN services s ON s.id = p.service_id
        WHERE p.trainer_id = :tid
    """
    if active_only:
        q += " AND p.is_active = true"
    q += " ORDER BY p.sort_order, p.id"
    r = await session.execute(text(q), {"tid": trainer_id})
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "name": row[2],
            "sessions_total": row[3],
            "price_cents": row[4],
            "service_id": row[5],
            "is_active": row[6],
            "sort_order": row[7],
            "created_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
            "service_name": (row[9] or "").strip() or None,
        }
        for row in rows
    ]


async def create_pass_product(
    session: AsyncSession,
    trainer_id: int,
    *,
    name: str,
    sessions_total: int,
    price_cents: int,
    service_id: int | None = None,
    sort_order: int = 0,
) -> int:
    """Create a pass product. Returns product id."""
    r = await session.execute(
        text("""
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, service_id, sort_order)
            VALUES (:tid, :name, :sessions_total, :price_cents, :service_id, :sort_order)
            RETURNING id
        """),
        {
            "tid": trainer_id,
            "name": name[:128],
            "sessions_total": sessions_total,
            "price_cents": price_cents,
            "service_id": service_id,
            "sort_order": sort_order,
        },
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def get_pass_product(session: AsyncSession, product_id: int, trainer_id: int) -> dict | None:
    """Get one product by id; must belong to trainer. Includes service_name."""
    r = await session.execute(
        text("""
            SELECT p.id, p.trainer_id, p.name, p.sessions_total, p.price_cents, p.service_id, p.is_active, p.sort_order,
                   COALESCE(s.name, '') AS service_name
            FROM trainer_pass_products p
            LEFT JOIN services s ON s.id = p.service_id
            WHERE p.id = :id AND p.trainer_id = :tid
        """),
        {"id": product_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "trainer_id": row[1],
        "name": row[2],
        "sessions_total": row[3],
        "price_cents": row[4],
        "service_id": row[5],
        "is_active": row[6],
        "sort_order": row[7],
        "service_name": (row[8] or "").strip() or None,
    }


async def update_pass_product(
    session: AsyncSession,
    product_id: int,
    trainer_id: int,
    *,
    name: str | None = None,
    sessions_total: int | None = None,
    price_cents: int | None = None,
    service_id: int | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> bool:
    """Update product fields. Only provided fields are changed. Returns True if updated."""
    updates = []
    params = {"id": product_id, "tid": trainer_id}
    if name is not None:
        updates.append("name = :name")
        params["name"] = name[:128]
    if sessions_total is not None:
        updates.append("sessions_total = :sessions_total")
        params["sessions_total"] = sessions_total
    if price_cents is not None:
        updates.append("price_cents = :price_cents")
        params["price_cents"] = price_cents
    if service_id is not None:
        updates.append("service_id = :service_id")
        params["service_id"] = service_id
    if is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = is_active
    if sort_order is not None:
        updates.append("sort_order = :sort_order")
        params["sort_order"] = sort_order
    if not updates:
        return True
    updates.append("updated_at = CURRENT_TIMESTAMP")
    q = f"""
        UPDATE trainer_pass_products
        SET {", ".join(updates)}
        WHERE id = :id AND trainer_id = :tid
    """
    r = await session.execute(text(q), params)
    ok = r.rowcount > 0
    if ok:
        await session.commit()
    return ok


async def delete_pass_product(session: AsyncSession, product_id: int, trainer_id: int) -> bool:
    """Delete product. Fails if pass_instances exist (RESTRICT). Returns True if deleted."""
    r = await session.execute(
        text("DELETE FROM trainer_pass_products WHERE id = :id AND trainer_id = :tid RETURNING id"),
        {"id": product_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    if deleted:
        await session.commit()
    return deleted


async def list_pass_instances_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> list[dict]:
    """List pass instances for this client issued by this trainer (product belongs to trainer). Active and used_up."""
    r = await session.execute(
        text("""
            SELECT
                pi.id,
                pi.pass_product_id,
                pi.sessions_remaining,
                pi.sessions_total,
                pi.issued_at,
                pi.status,
                p.name AS product_name,
                p.price_cents
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id AND p.trainer_id = :tid
            WHERE pi.client_id = :cid
            ORDER BY pi.issued_at DESC
        """),
        {"tid": trainer_id, "cid": client_id},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "pass_product_id": row[1],
            "sessions_remaining": row[2],
            "sessions_total": row[3],
            "issued_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
            "status": row[5],
            "product_name": row[6],
            "price_cents": row[7],
        }
        for row in rows
    ]


async def list_client_pass_instances(
    session: AsyncSession,
    client_id: int,
) -> list[dict]:
    """
    List all pass instances for a client (for client-facing "My passes").
    Single query with JOINs: product, trainer profile name, service name. No N+1.
    Returns active and used_up; client sees trainer, service, sessions left, price per session.
    """
    r = await session.execute(
        text("""
            SELECT
                pi.id,
                pi.pass_product_id,
                pi.sessions_remaining,
                pi.sessions_total,
                pi.issued_at,
                pi.expires_at,
                pi.status,
                p.name AS product_name,
                p.price_cents,
                p.trainer_id,
                p.service_id,
                TRIM(COALESCE(prof.first_name, '') || ' ' || COALESCE(prof.last_name, '')) AS trainer_name,
                COALESCE(srv.name, '') AS service_name
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            LEFT JOIN trainer_profiles prof ON prof.trainer_id = p.trainer_id
            LEFT JOIN services srv ON srv.id = p.service_id
            WHERE pi.client_id = :cid
              AND pi.status IN ('active', 'used_up')
            ORDER BY pi.status ASC, pi.issued_at DESC
        """),
        {"cid": client_id},
    )
    rows = r.fetchall()
    out = []
    for row in rows:
        sessions_total = row[3] or 0
        price_cents = row[8] or 0
        price_per_session_cents = (price_cents // sessions_total) if sessions_total else 0
        issued_at = row[4]
        expires_at = row[5]
        out.append({
            "id": row[0],
            "pass_product_id": row[1],
            "sessions_remaining": row[2],
            "sessions_total": sessions_total,
            "issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
            "expires_at": expires_at.isoformat() if expires_at and hasattr(expires_at, "isoformat") else (str(expires_at) if expires_at else None),
            "status": row[6],
            "product_name": (row[7] or "").strip() or "—",
            "price_cents": price_cents,
            "price_per_session_cents": price_per_session_cents,
            "trainer_id": row[9],
            "service_id": row[10],
            "trainer_name": (row[11] or "").strip() or "Тренер",
            "service_name": (row[12] or "").strip() or "—",
        })
    return out


async def issue_pass_to_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    pass_product_id: int,
) -> dict:
    """
    Issue a pass to a client (trainer recorded external payment). Creates pass_instance.
    Raises ValueError with message if product not found/inactive, client not found, or client has no booking with this trainer.
    Returns created instance with product name, sessions_total, sessions_remaining, issued_at, id.
    """
    product = await get_pass_product(session, pass_product_id, trainer_id)
    if not product:
        raise ValueError("Product not found or not yours")
    if not product.get("is_active"):
        raise ValueError("Product is inactive")
    # Client must exist and have at least one non-cancelled booking with this trainer
    r = await session.execute(
        text("""
            SELECT 1 FROM bookings b
            WHERE b.trainer_id = :tid AND b.client_id = :cid
              AND b.status NOT IN ('cancelled', 'declined')
            LIMIT 1
        """),
        {"tid": trainer_id, "cid": client_id},
    )
    if not r.fetchone():
        raise ValueError("Client not found or has no sessions with you — add a booking first")
    # Do not issue a second pass if client already has an active one for this trainer
    r = await session.execute(
        text("""
            SELECT 1 FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.client_id = :cid AND p.trainer_id = :tid
              AND pi.status = 'active' AND pi.sessions_remaining > 0
            LIMIT 1
        """),
        {"cid": client_id, "tid": trainer_id},
    )
    if r.fetchone():
        raise ValueError("У клиента уже есть активный абонемент")
    sessions_total = product["sessions_total"]
    r = await session.execute(
        text("""
            INSERT INTO pass_instances (client_id, pass_product_id, sessions_remaining, sessions_total, status)
            VALUES (:cid, :pid, :rem, :total, 'active')
            RETURNING id, client_id, pass_product_id, sessions_remaining, sessions_total, issued_at, status
        """),
        {
            "cid": client_id,
            "pid": pass_product_id,
            "rem": sessions_total,
            "total": sessions_total,
        },
    )
    row = r.fetchone()
    await session.commit()
    issued_at = row[5]
    return {
        "id": row[0],
        "client_id": row[1],
        "pass_product_id": row[2],
        "sessions_remaining": row[3],
        "sessions_total": row[4],
        "issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
        "status": row[6],
        "product_name": product["name"],
        "price_cents": product["price_cents"],
        "service_name": product.get("service_name"),
        "service_id": product.get("service_id"),
    }


async def redeem_pass_session_for_booking(
    session: AsyncSession,
    booking_id: int,
    *,
    allow_booking_statuses: frozenset[str] | None = None,
) -> bool:
    """
    Deduct one pass session for a completed booking. Called when booking status becomes completed.
    Finds an active pass_instance for this client+trainer (service match or product.service_id IS NULL),
    decrements sessions_remaining; if 0, sets status to used_up. If no suitable pass, returns False (no error).
    ``allow_booking_statuses`` extends the default (``completed`` only), e.g. ``no_show`` for problem E4 redemption.
    Returns True if a session was redeemed.
    """
    allowed = allow_booking_statuses if allow_booking_statuses is not None else frozenset({"completed"})
    r = await session.execute(
        text("""
            SELECT id, client_id, trainer_id, service_id, status
            FROM bookings WHERE id = :bid
        """),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row or (row[4] or "").strip().lower() not in allowed:
        return False
    client_id, trainer_id, service_id = row[1], row[2], row[3]
    # Pick one active pass: same trainer, service match or product.service_id IS NULL, sessions_remaining > 0
    r = await session.execute(
        text("""
            SELECT pi.id, pi.sessions_remaining
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.client_id = :cid AND p.trainer_id = :tid
              AND pi.status = 'active' AND pi.sessions_remaining > 0
              AND (p.service_id = :sid OR p.service_id IS NULL)
            ORDER BY pi.expires_at ASC NULLS LAST, pi.sessions_remaining ASC
            LIMIT 1
        """),
        {"cid": client_id, "tid": trainer_id, "sid": service_id},
    )
    inst = r.fetchone()
    if not inst:
        return False
    inst_id, rem = inst[0], inst[1]
    new_rem = rem - 1
    new_status = "used_up" if new_rem <= 0 else "active"
    await session.execute(
        text("""
            UPDATE pass_instances SET sessions_remaining = :rem, status = :st WHERE id = :id
        """),
        {"rem": new_rem, "st": new_status, "id": inst_id},
    )
    await session.execute(
        text("""
            INSERT INTO pass_redemptions (booking_id, pass_instance_id)
            VALUES (:bid, :inst_id)
            ON CONFLICT (booking_id) DO NOTHING
        """),
        {"bid": booking_id, "inst_id": inst_id},
    )
    return True
