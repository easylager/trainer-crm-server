"""
Pass products: trainer-defined subscription products (e.g. 5 sessions for 200 BYN).
Scopes: zero linked services = all trainer catalog services; non-empty junction = listed services only.
        zero linked tiers   = all price tier kinds;      non-empty junction = listed tier_kinds only.
Both scope conditions are ANDed: a booking must satisfy both service and tier filters to deduct a session.
Used by trainer Mini App, client catalog, redemption on completed bookings.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.price_tier_kind import VALID_PRICE_TIER_KINDS, PRICE_TIER_LABEL_RU, PRICE_TIER_ORDER

# SQL predicate: does pass product 'p' cover this booking's service AND tier?
# Params required: :booking_service_id (int), :booking_tier_kind (str | NULL)
#
# Service scope:  no rows in junction → unrestricted; otherwise must match booking.service_id
# Tier scope:     no rows in junction → unrestricted; otherwise booking.price_tier_kind must be non-NULL and match
SQL_PASS_PRODUCT_COVERS_BOOKING = """(
    (
        NOT EXISTS (
            SELECT 1 FROM trainer_pass_product_services t_svc
            WHERE t_svc.pass_product_id = p.id
        )
        OR EXISTS (
            SELECT 1 FROM trainer_pass_product_services t_svc
            WHERE t_svc.pass_product_id = p.id
              AND t_svc.service_id = CAST(:booking_service_id AS INTEGER)
        )
    )
    AND (
        NOT EXISTS (
            SELECT 1 FROM trainer_pass_product_tiers t_tier
            WHERE t_tier.pass_product_id = p.id
        )
        OR (
            :booking_tier_kind IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM trainer_pass_product_tiers t_tier
                WHERE t_tier.pass_product_id = p.id
                  AND t_tier.tier_kind = :booking_tier_kind
            )
        )
    )
)"""

# Legacy alias — callers that only pass booking_service_id still work if they add booking_tier_kind=None.
# All internal callers are updated to pass both params.
SQL_PASS_PRODUCT_COVERS_BOOKING_SERVICE = SQL_PASS_PRODUCT_COVERS_BOOKING

# Sale price frozen at issue time; COALESCE fallback for rows predating price_cents column.
SQL_PASS_INSTANCE_SALE_PRICE_CENTS = "COALESCE(pi.price_cents, p.price_cents, 0)"


async def _normalized_trainer_pass_service_ids(
    session: AsyncSession,
    trainer_id: int,
    raw_ids: list[int],
) -> list[int]:
    """Deduped sorted ids that exist on trainer_services; raises ValueError if any id invalid."""
    ids = sorted({int(x) for x in raw_ids if x is not None})
    if not ids:
        return []
    r = await session.execute(
        text(
            """
            SELECT ts.service_id FROM trainer_services ts
            WHERE ts.trainer_id = :tid AND ts.service_id = ANY(CAST(:sids AS INTEGER[]))
            """
        ),
        {"tid": trainer_id, "sids": ids},
    )
    found = {row[0] for row in r.fetchall()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError("Одна или несколько услуг не входят в ваш каталог")
    return ids


async def _replace_pass_product_services(
    session: AsyncSession,
    *,
    pass_product_id: int,
    trainer_id: int,
    service_ids: list[int],
) -> None:
    validated = await _normalized_trainer_pass_service_ids(session, trainer_id, service_ids)
    await session.execute(
        text("DELETE FROM trainer_pass_product_services WHERE pass_product_id = :pid"),
        {"pid": pass_product_id},
    )
    for sid in validated:
        await session.execute(
            text(
                """
                INSERT INTO trainer_pass_product_services (pass_product_id, service_id)
                VALUES (:pid, :sid)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pid": pass_product_id, "sid": sid},
        )


def _normalized_tier_kinds(raw: list[str]) -> list[str]:
    """Deduplicated, ordered, validated tier_kind values. Unknown values are silently dropped."""
    seen = {k for k in raw if k in VALID_PRICE_TIER_KINDS}
    return [k for k in PRICE_TIER_ORDER if k in seen]


async def _replace_pass_product_tiers(
    session: AsyncSession,
    *,
    pass_product_id: int,
    tier_kinds: list[str],
) -> None:
    """Replace tier junction rows atomically. Empty list = unrestricted (all tiers)."""
    validated = _normalized_tier_kinds(tier_kinds)
    await session.execute(
        text("DELETE FROM trainer_pass_product_tiers WHERE pass_product_id = :pid"),
        {"pid": pass_product_id},
    )
    for kind in validated:
        await session.execute(
            text(
                """
                INSERT INTO trainer_pass_product_tiers (pass_product_id, tier_kind)
                VALUES (:pid, :kind)
                ON CONFLICT DO NOTHING
                """
            ),
            {"pid": pass_product_id, "kind": kind},
        )


def enrich_pass_items_with_catalog_reference_prices(
    items: list[dict],
    *,
    price_by_service: dict[int, int],
    default_single_reference: int | None,
) -> None:
    """Mutates items with price_per_session_cents, pass_price_per_session_cents, savings_* (catalog UX)."""
    for p in items:
        sids = p.get("service_ids") or []
        if sids:
            priced = [price_by_service[s] for s in sids if s in price_by_service]
            single = min(priced) if priced else default_single_reference
        else:
            single = default_single_reference
        p["price_per_session_cents"] = single
        if p.get("sessions_total") and p.get("price_cents"):
            p["pass_price_per_session_cents"] = int(p["price_cents"]) // int(p["sessions_total"])
        else:
            p["pass_price_per_session_cents"] = None
        if single is not None and p.get("sessions_total") and p.get("price_cents"):
            pass_per_session = int(p["price_cents"]) // int(p["sessions_total"])
            savings = int(single) - pass_per_session
            p["savings_per_session_cents"] = max(0, savings)
            p["savings_total_cents"] = max(0, savings) * int(p["sessions_total"])
        else:
            p["savings_per_session_cents"] = None
            p["savings_total_cents"] = None


async def list_pass_products(session: AsyncSession, trainer_id: int, active_only: bool = False) -> list[dict]:
    """List pass products. service_ids/tier_kinds empty = unrestricted; labels for UI."""
    q = """
        SELECT
            p.id,
            p.trainer_id,
            p.name,
            p.sessions_total,
            p.price_cents,
            p.is_active,
            p.sort_order,
            p.created_at,
            COALESCE(
                (
                    SELECT ARRAY_AGG(sub.service_id ORDER BY sub.service_id)
                    FROM trainer_pass_product_services AS sub
                    WHERE sub.pass_product_id = p.id
                ),
                CAST(ARRAY[] AS INTEGER[])
            ) AS service_ids,
            COALESCE(
                (
                    SELECT STRING_AGG(
                        COALESCE(NULLIF(TRIM(srv.name), ''), '#' || tps.service_id::text),
                        ', '
                        ORDER BY srv.name NULLS LAST, tps.service_id
                    )
                    FROM trainer_pass_product_services tps
                    LEFT JOIN services srv ON srv.id = tps.service_id
                    WHERE tps.pass_product_id = p.id
                ),
                ''
            ) AS services_label,
            COALESCE(
                (
                    SELECT ARRAY_AGG(t.tier_kind ORDER BY t.tier_kind)
                    FROM trainer_pass_product_tiers AS t
                    WHERE t.pass_product_id = p.id
                ),
                CAST(ARRAY[] AS TEXT[])
            ) AS tier_kinds
        FROM trainer_pass_products p
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
            "is_active": row[5],
            "sort_order": row[6],
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
            "service_ids": list(row[8] or []),
            "service_name": (row[9] or "").strip() or None,
            # tier_kinds sorted by canonical PRICE_TIER_ORDER (not DB sort)
            "tier_kinds": [k for k in PRICE_TIER_ORDER if k in set(row[10] or [])],
            "tiers_label": ", ".join(
                PRICE_TIER_LABEL_RU[k] for k in PRICE_TIER_ORDER if k in set(row[10] or [])
            ) or None,
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
    service_ids: list[int] | None = None,
    tier_kinds: list[str] | None = None,
    sort_order: int = 0,
) -> int:
    """Create a pass product. Empty service_ids/tier_kinds = unrestricted. Returns product id."""
    validated_svc = await _normalized_trainer_pass_service_ids(session, trainer_id, service_ids or [])
    validated_tiers = _normalized_tier_kinds(tier_kinds or [])
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_pass_products (trainer_id, name, sessions_total, price_cents, sort_order)
            VALUES (:tid, :name, :sessions_total, :price_cents, :sort_order)
            RETURNING id
            """
        ),
        {
            "tid": trainer_id,
            "name": name[:128],
            "sessions_total": sessions_total,
            "price_cents": price_cents,
            "sort_order": sort_order,
        },
    )
    (pk,) = r.fetchone()
    for sid in validated_svc:
        await session.execute(
            text(
                """
                INSERT INTO trainer_pass_product_services (pass_product_id, service_id)
                VALUES (:pid, :sid)
                """
            ),
            {"pid": pk, "sid": sid},
        )
    for kind in validated_tiers:
        await session.execute(
            text(
                """
                INSERT INTO trainer_pass_product_tiers (pass_product_id, tier_kind)
                VALUES (:pid, :kind)
                """
            ),
            {"pid": pk, "kind": kind},
        )
    await session.commit()
    return pk


async def get_pass_product(session: AsyncSession, product_id: int, trainer_id: int) -> dict | None:
    """Get one product with service_ids and comma-joined service_name (None = unrestricted)."""
    items = await list_pass_products(session, trainer_id, active_only=False)
    for it in items:
        if int(it["id"]) == int(product_id):
            return it
    return None


async def update_pass_product(
    session: AsyncSession,
    product_id: int,
    trainer_id: int,
    *,
    name: str | None = None,
    sessions_total: int | None = None,
    price_cents: int | None = None,
    service_ids: list[int] | None = None,
    tier_kinds: list[str] | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> bool:
    """Update product. service_ids/tier_kinds replace junction when provided (empty list = unrestricted)."""
    needs_ownership_check = service_ids is not None or tier_kinds is not None
    if needs_ownership_check:
        ex = await session.execute(
            text("SELECT 1 FROM trainer_pass_products WHERE id = :id AND trainer_id = :tid"),
            {"id": product_id, "tid": trainer_id},
        )
        if not ex.fetchone():
            return False
        if service_ids is not None:
            await _normalized_trainer_pass_service_ids(session, trainer_id, service_ids)
    updates = []
    params: dict = {"id": product_id, "tid": trainer_id}
    if name is not None:
        updates.append("name = :name")
        params["name"] = name[:128]
    if sessions_total is not None:
        updates.append("sessions_total = :sessions_total")
        params["sessions_total"] = sessions_total
    if price_cents is not None:
        updates.append("price_cents = :price_cents")
        params["price_cents"] = price_cents
    if is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = is_active
    if sort_order is not None:
        updates.append("sort_order = :sort_order")
        params["sort_order"] = sort_order
    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        q = f"""
            UPDATE trainer_pass_products
            SET {", ".join(updates)}
            WHERE id = :id AND trainer_id = :tid
        """
        r = await session.execute(text(q), params)
        if r.rowcount == 0:
            return False
    if service_ids is not None:
        await _replace_pass_product_services(
            session,
            pass_product_id=product_id,
            trainer_id=trainer_id,
            service_ids=service_ids,
        )
    if tier_kinds is not None:
        await _replace_pass_product_tiers(
            session,
            pass_product_id=product_id,
            tier_kinds=tier_kinds,
        )
    if updates or service_ids is not None or tier_kinds is not None:
        await session.commit()
        return True
    return True


async def delete_pass_product(session: AsyncSession, product_id: int, trainer_id: int) -> bool:
    """Delete product. CASCADE clears junction rows. Fails if pass_instances exist (RESTRICT)."""
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
    """List pass instances for client (trainer-scoped products). Adds services_display."""
    r = await session.execute(
        text(
            """
            SELECT
                pi.id,
                pi.pass_product_id,
                pi.sessions_remaining,
                pi.sessions_total,
                pi.issued_at,
                pi.status,
                p.name AS product_name,
                pi.price_cents,
                COALESCE(
                    (
                        SELECT STRING_AGG(
                            COALESCE(NULLIF(TRIM(srv.name), ''), '#' || tps.service_id::text),
                            ', '
                            ORDER BY srv.name NULLS LAST, tps.service_id
                        )
                        FROM trainer_pass_product_services tps
                        LEFT JOIN services srv ON srv.id = tps.service_id
                        WHERE tps.pass_product_id = p.id
                    ),
                    ''
                ) AS scope_label
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id AND p.trainer_id = :tid
            WHERE pi.client_id = :cid
            ORDER BY pi.issued_at DESC
            """
        ),
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
            "service_name": (row[8] or "").strip() or None,
        }
        for row in rows
    ]


async def list_client_pass_instances(
    session: AsyncSession,
    client_id: int,
) -> list[dict]:
    """
    Client-facing «Мои абонементы»: aggregated service scope label (comma-separated or None).
    """
    r = await session.execute(
        text(
            """
            SELECT
                pi.id,
                pi.pass_product_id,
                pi.sessions_remaining,
                pi.sessions_total,
                pi.issued_at,
                pi.expires_at,
                pi.status,
                p.name AS product_name,
                pi.price_cents,
                p.trainer_id,
                COALESCE(
                    (
                        SELECT ARRAY_AGG(sub.service_id ORDER BY sub.service_id)
                        FROM trainer_pass_product_services AS sub
                        WHERE sub.pass_product_id = p.id
                    ),
                    CAST(ARRAY[] AS INTEGER[])
                ) AS svc_ids,
                TRIM(COALESCE(prof.first_name, '') || ' ' || COALESCE(prof.last_name, '')) AS trainer_name,
                COALESCE(
                    (
                        SELECT STRING_AGG(
                            COALESCE(NULLIF(TRIM(srv.name), ''), '#' || tps.service_id::text),
                            ', '
                            ORDER BY srv.name NULLS LAST, tps.service_id
                        )
                        FROM trainer_pass_product_services tps
                        LEFT JOIN services srv ON srv.id = tps.service_id
                        WHERE tps.pass_product_id = p.id
                    ),
                    ''
                ) AS svc_scope_label
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            LEFT JOIN trainer_profiles prof ON prof.trainer_id = p.trainer_id
            WHERE pi.client_id = :cid
              AND pi.status IN ('active', 'used_up')
            ORDER BY pi.status ASC, pi.issued_at DESC
            """
        ),
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
        label = (row[12] or "").strip()
        out.append(
            {
                "id": row[0],
                "pass_product_id": row[1],
                "sessions_remaining": row[2],
                "sessions_total": sessions_total,
                "issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
                "expires_at": expires_at.isoformat()
                if expires_at and hasattr(expires_at, "isoformat")
                else (str(expires_at) if expires_at else None),
                "status": row[6],
                "product_name": (row[7] or "").strip() or "—",
                "price_cents": price_cents,
                "price_per_session_cents": price_per_session_cents,
                "trainer_id": row[9],
                "service_ids": list(row[10] or []),
                "trainer_name": (row[11] or "").strip() or "Тренер",
                "service_name": label if label else None,
            }
        )
    return out


async def _trainer_may_issue_pass_to_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
) -> tuple[bool, str | None]:
    """
    Pass issue is not tied to active bookings: roster link, any booking history,
    or active/trial training group is enough.
    """
    r = await session.execute(
        text(
            """
            SELECT
              EXISTS (SELECT 1 FROM clients c WHERE c.id = :cid) AS client_exists,
              (
                EXISTS (
                    SELECT 1 FROM trainer_client_roster r
                    WHERE r.trainer_id = :tid AND r.client_id = :cid
                )
                OR EXISTS (
                    SELECT 1 FROM bookings b
                    WHERE b.trainer_id = :tid AND b.client_id = :cid
                )
                OR EXISTS (
                    SELECT 1 FROM training_group_members m
                    INNER JOIN training_groups g ON g.id = m.training_group_id
                    WHERE g.trainer_id = :tid AND m.client_id = :cid
                      AND m.status IN ('active', 'trial')
                )
              ) AS in_scope
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    row = r.fetchone()
    if not row or not row[0]:
        return False, "Клиент не найден"
    if not row[1]:
        return False, "Клиент не привязан к вашему кабинету"
    return True, None


async def issue_pass_to_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    pass_product_id: int,
) -> dict:
    """
    Issue pass_instance after external payment.
    Returns snapshot including service_names for client notification HTML.
    """
    product = await get_pass_product(session, pass_product_id, trainer_id)
    if not product:
        raise ValueError("Product not found or not yours")
    if not product.get("is_active"):
        raise ValueError("Product is inactive")
    may_issue, scope_err = await _trainer_may_issue_pass_to_client(session, trainer_id, client_id)
    if not may_issue:
        raise ValueError(scope_err or "Клиент не привязан к вашему кабинету")
    r = await session.execute(
        text(
            """
            SELECT 1 FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.client_id = :cid AND p.trainer_id = :tid
              AND pi.status = 'active' AND pi.sessions_remaining > 0
            LIMIT 1
            """
        ),
        {"cid": client_id, "tid": trainer_id},
    )
    if r.fetchone():
        raise ValueError("У клиента уже есть активный абонемент")
    sessions_total = product["sessions_total"]
    sale_price_cents = int(product["price_cents"])
    r = await session.execute(
        text(
            """
            INSERT INTO pass_instances (
                client_id, pass_product_id, sessions_remaining, sessions_total, price_cents, status
            )
            VALUES (:cid, :pid, :rem, :total, :price, 'active')
            RETURNING id, client_id, pass_product_id, sessions_remaining, sessions_total, issued_at, status
            """
        ),
        {
            "cid": client_id,
            "pid": pass_product_id,
            "rem": sessions_total,
            "total": sessions_total,
            "price": sale_price_cents,
        },
    )
    row = r.fetchone()
    await session.commit()
    issued_at = row[5]

    svc_ids = product.get("service_ids") or []
    service_names: list[str] = []
    if svc_ids:
        rnm = await session.execute(
            text(
                """
                SELECT s.id, COALESCE(NULLIF(TRIM(s.name), ''), '')
                FROM services s WHERE s.id = ANY(CAST(:sids AS INTEGER[]))
                ORDER BY s.name NULLS LAST, s.id
                """
            ),
            {"sids": list(svc_ids)},
        )
        for sid, nm in rnm.fetchall():
            service_names.append((nm or "").strip() or f"#{sid}")

    return {
        "id": row[0],
        "client_id": row[1],
        "pass_product_id": row[2],
        "sessions_remaining": row[3],
        "sessions_total": row[4],
        "issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
        "status": row[6],
        "product_name": product["name"],
        "price_cents": sale_price_cents,
        "service_names": service_names,
    }


async def redeem_pass_session_for_booking(
    session: AsyncSession,
    booking_id: int,
    *,
    allow_booking_statuses: frozenset[str] | None = None,
) -> bool:
    """
    Deduct one session from the most-expiring eligible pass.

    Scope matching (both must pass):
      - service scope: pass unrestricted OR booking.service_id in junction
      - tier scope:    pass unrestricted OR (booking.price_tier_kind IS NOT NULL AND in junction)
    A booking without a price_tier_kind cannot satisfy a tier-restricted pass — financially correct.
    """
    allowed = allow_booking_statuses if allow_booking_statuses is not None else frozenset({"completed"})
    r = await session.execute(
        text(
            "SELECT id, client_id, trainer_id, service_id, status, price_tier_kind"
            " FROM bookings WHERE id = :bid"
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row or (row[4] or "").strip().lower() not in allowed:
        return False
    client_id, trainer_id, service_id = row[1], row[2], row[3]
    # price_tier_kind may be NULL for bookings made without a tier variant
    tier_kind: str | None = row[5] if row[5] else None
    r = await session.execute(
        text(
            f"""
            SELECT pi.id, pi.sessions_remaining
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.client_id = :cid AND p.trainer_id = :tid
              AND pi.status = 'active' AND pi.sessions_remaining > 0
              AND {SQL_PASS_PRODUCT_COVERS_BOOKING}
            ORDER BY pi.expires_at ASC NULLS LAST, pi.sessions_remaining ASC
            LIMIT 1
            """
        ),
        {
            "cid": client_id,
            "tid": trainer_id,
            "booking_service_id": service_id,
            "booking_tier_kind": tier_kind,
        },
    )
    inst = r.fetchone()
    if not inst:
        return False
    inst_id, rem = inst[0], inst[1]
    new_rem = rem - 1
    new_status = "used_up" if new_rem <= 0 else "active"
    await session.execute(
        text("UPDATE pass_instances SET sessions_remaining = :rem, status = :st WHERE id = :id"),
        {"rem": new_rem, "st": new_status, "id": inst_id},
    )
    await session.execute(
        text(
            """
            INSERT INTO pass_redemptions (booking_id, pass_instance_id)
            VALUES (:bid, :inst_id)
            ON CONFLICT (booking_id) DO NOTHING
            """
        ),
        {"bid": booking_id, "inst_id": inst_id},
    )
    return True

