"""
Pass products: trainer-defined subscription products (e.g. 5 sessions for 200 BYN).
Scopes: zero linked services = all trainer catalog services; non-empty junction = listed services only.
        zero linked tiers   = all price tier kinds;      non-empty junction = listed tier_kinds only.
Both scope conditions are ANDed: a booking must satisfy both service and tier filters to deduct a session.
Used by trainer Mini App, client catalog, redemption on completed bookings.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import NOTIFICATION_TZ

from src.shared.price_tier_kind import (
    VALID_PRICE_TIER_KINDS,
    PRICE_TIER_LABEL_RU,
    PRICE_TIER_ORDER,
    normalize_price_tier_kind,
)

logger = logging.getLogger(__name__)

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
            CAST(:booking_tier_kind AS TEXT) IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM trainer_pass_product_tiers t_tier
                WHERE t_tier.pass_product_id = p.id
                  AND t_tier.tier_kind = CAST(:booking_tier_kind AS TEXT)
            )
        )
    )
)"""

# Same predicate wired to bookings alias `b` (for listing redeemable sessions).
SQL_PASS_PRODUCT_COVERS_BOOKING_ROW = """(
    (
        NOT EXISTS (
            SELECT 1 FROM trainer_pass_product_services t_svc
            WHERE t_svc.pass_product_id = p.id
        )
        OR EXISTS (
            SELECT 1 FROM trainer_pass_product_services t_svc
            WHERE t_svc.pass_product_id = p.id
              AND t_svc.service_id = b.service_id
        )
    )
    AND (
        NOT EXISTS (
            SELECT 1 FROM trainer_pass_product_tiers t_tier
            WHERE t_tier.pass_product_id = p.id
        )
        OR (
            b.price_tier_kind IS NOT NULL
            AND EXISTS (
                SELECT 1 FROM trainer_pass_product_tiers t_tier
                WHERE t_tier.pass_product_id = p.id
                  AND t_tier.tier_kind = b.price_tier_kind
            )
        )
    )
)"""

# Legacy alias — callers that only pass booking_service_id still work if they add booking_tier_kind=None.
# All internal callers are updated to pass both params.
SQL_PASS_PRODUCT_COVERS_BOOKING_SERVICE = SQL_PASS_PRODUCT_COVERS_BOOKING

# Sale price frozen at issue time; COALESCE fallback for rows predating price_cents column.
SQL_PASS_INSTANCE_SALE_PRICE_CENTS = "COALESCE(pi.price_cents, p.price_cents, 0)"

_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"


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


async def get_trainer_service_tier_kinds_by_service(
    session: AsyncSession,
    trainer_id: int,
) -> dict[int, set[str]]:
    """Catalog service_id → tier_kind values configured in trainer profile."""
    r = await session.execute(
        text(
            """
            SELECT service_id, tier_kind
            FROM trainer_service_price_variants
            WHERE trainer_id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    out: dict[int, set[str]] = {}
    for sid_raw, tk_raw in r.fetchall():
        kind = normalize_price_tier_kind(tk_raw)
        if not kind:
            continue
        out.setdefault(int(sid_raw), set()).add(kind)
    return out


async def _trainer_catalog_service_ids(session: AsyncSession, trainer_id: int) -> list[int]:
    r = await session.execute(
        text(
            """
            SELECT service_id FROM trainer_services
            WHERE trainer_id = :tid
            ORDER BY service_id
            """
        ),
        {"tid": trainer_id},
    )
    return [int(row[0]) for row in r.fetchall()]


async def _service_names_by_ids(session: AsyncSession, service_ids: list[int]) -> dict[int, str]:
    if not service_ids:
        return {}
    r = await session.execute(
        text(
            """
            SELECT id, COALESCE(NULLIF(TRIM(name), ''), '')
            FROM services
            WHERE id = ANY(CAST(:sids AS INTEGER[]))
            """
        ),
        {"sids": list(sorted(set(service_ids)))},
    )
    return {int(row[0]): (row[1] or "").strip() or f"#{row[0]}" for row in r.fetchall()}


def collect_pass_product_scope_issues(
    *,
    service_ids: list[int],
    tier_kinds: list[str],
    tiers_by_service: dict[int, set[str]],
    service_names: dict[int, str],
) -> list[str]:
    """
    Pass scope must be bookable: each listed tier must exist on every listed service.
    Unrestricted services + restricted tiers → tier must exist on at least one catalog service.
    """
    if not tier_kinds:
        return []
    issues: list[str] = []
    if service_ids:
        for sid in service_ids:
            configured = tiers_by_service.get(int(sid), set())
            svc_name = service_names.get(int(sid), f"#{sid}")
            for kind in tier_kinds:
                if kind not in configured:
                    label = PRICE_TIER_LABEL_RU.get(kind, kind)
                    issues.append(f"Тариф «{label}» не настроен для услуги «{svc_name}»")
        return issues
    all_profile_tiers: set[str] = set()
    for tier_set in tiers_by_service.values():
        all_profile_tiers |= tier_set
    for kind in tier_kinds:
        if kind not in all_profile_tiers:
            label = PRICE_TIER_LABEL_RU.get(kind, kind)
            issues.append(f"Тариф «{label}» не настроен ни для одной услуги в профиле")
    return issues


async def validate_pass_product_tier_scope(
    session: AsyncSession,
    trainer_id: int,
    service_ids: list[int],
    tier_kinds: list[str],
) -> None:
    """Raises ValueError when pass tier scope is not configured in trainer profile."""
    tiers = _normalized_tier_kinds(tier_kinds)
    if not tiers:
        return
    tiers_by_service = await get_trainer_service_tier_kinds_by_service(session, trainer_id)
    scoped_services = sorted({int(x) for x in service_ids if x is not None})
    if not scoped_services:
        scoped_services = await _trainer_catalog_service_ids(session, trainer_id)
    service_names = await _service_names_by_ids(session, scoped_services)
    issues = collect_pass_product_scope_issues(
        service_ids=scoped_services if service_ids else [],
        tier_kinds=tiers,
        tiers_by_service=tiers_by_service,
        service_names=service_names,
    )
    if issues:
        detail = issues[0] if len(issues) == 1 else issues[0] + f" (и ещё {len(issues) - 1})"
        raise ValueError(
            detail + ". Добавьте тариф в профиле или измените условия абонемента."
        )


async def enrich_pass_products_with_scope_health(
    session: AsyncSession,
    trainer_id: int,
    items: list[dict],
) -> None:
    """Mutates list items with scope_valid / scope_issues for trainer UI warnings."""
    if not items:
        return
    tiers_by_service = await get_trainer_service_tier_kinds_by_service(session, trainer_id)
    all_sids: set[int] = set()
    for it in items:
        all_sids.update(int(x) for x in (it.get("service_ids") or []))
    service_names = await _service_names_by_ids(session, list(all_sids))
    for it in items:
        svc_ids = [int(x) for x in (it.get("service_ids") or [])]
        tier_kinds = list(it.get("tier_kinds") or [])
        issues = collect_pass_product_scope_issues(
            service_ids=svc_ids,
            tier_kinds=tier_kinds,
            tiers_by_service=tiers_by_service,
            service_names=service_names,
        )
        it["scope_valid"] = len(issues) == 0
        it["scope_issues"] = issues
        it["scope_warning"] = issues[0] if issues else None


async def _load_pass_product_scope_junctions(
    session: AsyncSession,
    pass_product_id: int,
) -> tuple[list[int], list[str]]:
    r_svc = await session.execute(
        text(
            """
            SELECT service_id FROM trainer_pass_product_services
            WHERE pass_product_id = :pid
            ORDER BY service_id
            """
        ),
        {"pid": pass_product_id},
    )
    r_tier = await session.execute(
        text(
            """
            SELECT tier_kind FROM trainer_pass_product_tiers
            WHERE pass_product_id = :pid
            ORDER BY tier_kind
            """
        ),
        {"pid": pass_product_id},
    )
    service_ids = [int(row[0]) for row in r_svc.fetchall()]
    tier_kinds = _normalized_tier_kinds([str(row[0]) for row in r_tier.fetchall()])
    return service_ids, tier_kinds


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
    items = [
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
    await enrich_pass_products_with_scope_health(session, trainer_id, items)
    return items


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
    await validate_pass_product_tier_scope(session, trainer_id, validated_svc, validated_tiers)
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
    scope_will_change = service_ids is not None or tier_kinds is not None
    if scope_will_change:
        ex = await session.execute(
            text("SELECT 1 FROM trainer_pass_products WHERE id = :id AND trainer_id = :tid"),
            {"id": product_id, "tid": trainer_id},
        )
        if not ex.fetchone():
            return False
        cur_svc, cur_tiers = await _load_pass_product_scope_junctions(session, product_id)
        eff_svc = list(service_ids) if service_ids is not None else cur_svc
        eff_tiers = list(tier_kinds) if tier_kinds is not None else cur_tiers
        await validate_pass_product_tier_scope(session, trainer_id, eff_svc, eff_tiers)
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

    Idempotent: if ``pass_redemptions`` already has this booking, returns True without a second debit.
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

    already = await session.execute(
        text("SELECT 1 FROM pass_redemptions WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if already.fetchone():
        return True

    cert = await session.execute(
        text("SELECT 1 FROM certificate_booking_credits WHERE booking_id = :bid"),
        {"bid": booking_id},
    )
    if cert.fetchone():
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
            FOR UPDATE OF pi
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
        logger.info(
            "pass redeem skipped booking_id=%s client_id=%s trainer_id=%s service_id=%s "
            "tier_kind=%s status=%s — no eligible active pass",
            booking_id,
            client_id,
            trainer_id,
            service_id,
            tier_kind,
            row[4],
        )
        return False
    inst_id, rem = int(inst[0]), int(inst[1])
    new_rem = rem - 1
    new_status = "used_up" if new_rem <= 0 else "active"
    inserted = await session.execute(
        text(
            """
            INSERT INTO pass_redemptions (booking_id, pass_instance_id)
            VALUES (:bid, :inst_id)
            ON CONFLICT (booking_id) DO NOTHING
            RETURNING id
            """
        ),
        {"bid": booking_id, "inst_id": inst_id},
    )
    if inserted.fetchone() is None:
        # Concurrent redeem won; do not double-debit remaining.
        return True
    await session.execute(
        text("UPDATE pass_instances SET sessions_remaining = :rem, status = :st WHERE id = :id"),
        {"rem": new_rem, "st": new_status, "id": inst_id},
    )
    logger.info(
        "pass redeem ok booking_id=%s pass_instance_id=%s remaining=%s",
        booking_id,
        inst_id,
        new_rem,
    )
    return True


def _iso_dt(value: object | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


async def get_trainer_pass_instance_detail(
    session: AsyncSession,
    trainer_id: int,
    pass_instance_id: int,
) -> dict | None:
    """Trainer-owned pass snapshot for detail / manual redemption screen."""
    r = await session.execute(
        text(
            f"""
            SELECT
                pi.id,
                pi.client_id,
                pi.sessions_remaining,
                pi.sessions_total,
                pi.issued_at,
                pi.expires_at,
                pi.status,
                p.id AS pass_product_id,
                p.name AS product_name,
                {SQL_PASS_INSTANCE_SALE_PRICE_CENTS} AS price_cents,
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
                ) AS scope_label,
                TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                c.phone
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id AND p.trainer_id = :tid
            JOIN clients c ON c.id = pi.client_id
            WHERE pi.id = :pid
            """
        ),
        {"tid": trainer_id, "pid": int(pass_instance_id)},
    )
    row = r.fetchone()
    if row is None:
        return None
    scope = (row[10] or "").strip() or None
    client_name = (row[11] or "").strip()
    client_id = int(row[1])
    return {
        "id": int(row[0]),
        "client_id": client_id,
        "client_name": client_name or f"Клиент #{client_id}",
        "client_phone": (row[12] or "").strip() or None,
        "sessions_remaining": int(row[2] or 0),
        "sessions_total": int(row[3] or 0),
        "issued_at": _iso_dt(row[4]),
        "expires_at": _iso_dt(row[5]),
        "status": str(row[6] or ""),
        "pass_product_id": int(row[7]),
        "product_name": (row[8] or "").strip() or "Абонемент",
        "price_cents": int(row[9] or 0),
        "service_scope": scope,
        "can_redeem": str(row[6]) == "active" and int(row[2] or 0) > 0,
    }


async def list_pass_redemptions_for_instance(
    session: AsyncSession,
    trainer_id: int,
    pass_instance_id: int,
    *,
    limit: int = 20,
) -> list[dict]:
    """Past sessions already debited from this pass (newest first)."""
    lim = max(1, min(int(limit or 20), 50))
    r = await session.execute(
        text(
            f"""
            SELECT
                pr.booking_id,
                pr.redeemed_at,
                s.slot_date,
                s.start_time,
                s.end_time,
                COALESCE(NULLIF(TRIM(srv.name), ''), 'Занятие') AS service_name
            FROM pass_redemptions pr
            JOIN pass_instances pi ON pi.id = pr.pass_instance_id
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id AND p.trainer_id = :tid
            JOIN bookings b ON b.id = pr.booking_id
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN services srv ON srv.id = b.service_id
            WHERE pr.pass_instance_id = :pid
            ORDER BY s.slot_date DESC, s.start_time DESC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "pid": int(pass_instance_id), "lim": lim},
    )
    out: list[dict] = []
    for row in r.fetchall():
        st = row[3]
        et = row[4]
        out.append(
            {
                "booking_id": int(row[0]),
                "redeemed_at": _iso_dt(row[1]),
                "slot_date": row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2]),
                "start_time": st.isoformat() if hasattr(st, "isoformat") else str(st),
                "end_time": et.isoformat() if hasattr(et, "isoformat") else str(et),
                "service_name": (row[5] or "").strip() or "Занятие",
            }
        )
    return out


async def list_redeemable_bookings_for_pass_instance(
    session: AsyncSession,
    trainer_id: int,
    pass_instance_id: int,
    *,
    limit: int = 30,
) -> dict:
    """
    Sessions of the pass owner without pass/cert payment, matching product scope.

    Includes:
      - ``completed`` bookings (even if the trainer marked them done before slot end)
      - ``confirmed`` / ``pending`` bookings whose slot has already ended (can complete+redeem)
    """
    detail = await get_trainer_pass_instance_detail(session, trainer_id, pass_instance_id)
    if detail is None:
        return {"error": "pass_not_found"}
    if not detail.get("can_redeem"):
        return {"error": "pass_not_redeemable", "pass": detail, "items": []}

    lim = max(1, min(int(limit or 30), 50))
    r = await session.execute(
        text(
            f"""
            SELECT
                b.id,
                s.slot_date,
                s.start_time,
                s.end_time,
                COALESCE(NULLIF(TRIM(srv.name), ''), 'Занятие') AS service_name,
                b.price_tier_kind,
                COALESCE(b.booking_price_cents, spv.price_cents, ts.price_cents, 0) AS price_cents,
                b.status
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN pass_instances pi ON pi.id = :pid
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id AND p.trainer_id = :tid
            LEFT JOIN services srv ON srv.id = b.service_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            LEFT JOIN trainer_service_price_variants spv ON spv.id = b.service_price_variant_id
            WHERE b.trainer_id = :tid
              AND b.client_id = pi.client_id
              AND b.status IN ('completed', 'confirmed', 'pending')
              AND NOT b.is_sandbox
              AND (
                    b.status = 'completed'
                    OR {_SQL_SLOT_END_TS} < CURRENT_TIMESTAMP
              )
              AND NOT EXISTS (SELECT 1 FROM pass_redemptions pr WHERE pr.booking_id = b.id)
              AND NOT EXISTS (
                  SELECT 1 FROM certificate_booking_credits cbc WHERE cbc.booking_id = b.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM booking_problem_reports bpr WHERE bpr.booking_id = b.id
              )
              AND {SQL_PASS_PRODUCT_COVERS_BOOKING_ROW}
            ORDER BY s.slot_date DESC, s.start_time DESC
            LIMIT :lim
            """
        ),
        {"tid": trainer_id, "pid": int(pass_instance_id), "lim": lim},
    )
    items: list[dict] = []
    for row in r.fetchall():
        st = row[2]
        et = row[3]
        status = (row[7] or "").strip().lower()
        items.append(
            {
                "booking_id": int(row[0]),
                "slot_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
                "start_time": st.isoformat() if hasattr(st, "isoformat") else str(st),
                "end_time": et.isoformat() if hasattr(et, "isoformat") else str(et),
                "service_name": (row[4] or "").strip() or "Занятие",
                "price_tier_kind": row[5],
                "price_cents": int(row[6] or 0),
                "booking_status": status,
                "needs_complete": status in ("confirmed", "pending"),
            }
        )
    return {"pass": detail, "items": items}


async def manual_redeem_pass_for_booking(
    session: AsyncSession,
    trainer_id: int,
    pass_instance_id: int,
    booking_id: int,
) -> dict:
    """
    Trainer applies a specific pass to a session (retroactive debit).

    Accepts ``completed`` bookings, and ``confirmed``/``pending`` whose slot has already ended
    (marks them completed first, then debits). Writes ``pass_redemptions`` so stats treat the
    visit as pass-covered.
    """
    r = await session.execute(
        text(
            """
            SELECT
                pi.id, pi.client_id, pi.sessions_remaining, pi.status, pi.expires_at,
                p.trainer_id
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.id = :pid
            FOR UPDATE OF pi
            """
        ),
        {"pid": int(pass_instance_id)},
    )
    inst = r.fetchone()
    if inst is None or int(inst[5]) != int(trainer_id):
        raise ValueError("Абонемент не найден")
    if str(inst[3]) != "active":
        raise ValueError("Абонемент не активен")
    rem = int(inst[2] or 0)
    if rem <= 0:
        raise ValueError("На абонементе не осталось занятий")

    expires = inst[4]
    if expires is not None:
        exp_dt = expires if isinstance(expires, datetime) else datetime.fromisoformat(str(expires))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt <= datetime.now(timezone.utc):
            raise ValueError("Срок абонемента истёк")

    client_id = int(inst[1])
    r_b = await session.execute(
        text(
            f"""
            SELECT b.id, b.client_id, b.trainer_id, b.service_id, b.status, b.price_tier_kind,
                   {_SQL_SLOT_END_TS} AS slot_end_ts
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.id = :bid
            FOR UPDATE OF b
            """
        ),
        {"bid": int(booking_id)},
    )
    booking = r_b.fetchone()
    if booking is None or int(booking[2]) != int(trainer_id):
        raise ValueError("Запись не найдена")
    if int(booking[1]) != client_id:
        raise ValueError("Запись принадлежит другому клиенту")

    status = str(booking[4] or "").strip().lower()
    slot_end = booking[6]
    now_utc = datetime.now(timezone.utc)
    if status == "completed":
        # Trainer may have marked the session done before wall-clock end — allow debit.
        pass
    elif status in ("confirmed", "pending"):
        if slot_end is not None and slot_end >= now_utc:
            raise ValueError("Занятие ещё не завершилось — дождитесь окончания или отметьте проведённым в расписании")
        pr = await session.execute(
            text("SELECT 1 FROM booking_problem_reports WHERE booking_id = :bid"),
            {"bid": int(booking_id)},
        )
        if pr.fetchone():
            raise ValueError("По записи есть отчёт о проблеме — сначала разберите его в расписании")
        await session.execute(
            text("UPDATE bookings SET status = 'completed' WHERE id = :bid"),
            {"bid": int(booking_id)},
        )
        status = "completed"
    else:
        raise ValueError("Списать можно только с проведённого или уже прошедшего занятия")

    chk_pr = await session.execute(
        text(
            """
            SELECT pass_instance_id FROM pass_redemptions WHERE booking_id = :bid
            """
        ),
        {"bid": int(booking_id)},
    )
    existing = chk_pr.fetchone()
    if existing:
        if int(existing[0]) == int(pass_instance_id):
            await session.commit()
            detail = await get_trainer_pass_instance_detail(session, trainer_id, pass_instance_id)
            return {"pass": detail, "already_redeemed": True}
        raise ValueError("Занятие уже списано с другого абонемента")

    chk_cert = await session.execute(
        text("SELECT 1 FROM certificate_booking_credits WHERE booking_id = :bid"),
        {"bid": int(booking_id)},
    )
    if chk_cert.fetchone():
        raise ValueError("Занятие оплачено сертификатом — списание с абонемента невозможно")

    service_id = int(booking[3]) if booking[3] is not None else None
    tier_kind: str | None = booking[5] if booking[5] else None
    if service_id is None:
        raise ValueError("У записи не указана услуга")

    r_scope = await session.execute(
        text(
            f"""
            SELECT 1
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            WHERE pi.id = :pid AND {SQL_PASS_PRODUCT_COVERS_BOOKING}
            """
        ),
        {
            "pid": int(pass_instance_id),
            "booking_service_id": service_id,
            "booking_tier_kind": tier_kind,
        },
    )
    if r_scope.fetchone() is None:
        raise ValueError(
            "Абонемент не покрывает эту услугу или тариф. "
            "Если абонемент ограничен тарифом (взрослый/детский), в записи должен быть тот же тариф."
        )

    new_rem = rem - 1
    new_status = "used_up" if new_rem <= 0 else "active"
    inserted = await session.execute(
        text(
            """
            INSERT INTO pass_redemptions (booking_id, pass_instance_id)
            VALUES (:bid, :inst_id)
            ON CONFLICT (booking_id) DO NOTHING
            RETURNING id
            """
        ),
        {"bid": int(booking_id), "inst_id": int(pass_instance_id)},
    )
    if inserted.fetchone() is None:
        await session.commit()
        detail = await get_trainer_pass_instance_detail(session, trainer_id, pass_instance_id)
        return {"pass": detail, "already_redeemed": True}

    await session.execute(
        text(
            """
            UPDATE pass_instances
            SET sessions_remaining = :rem, status = :st
            WHERE id = :id
            """
        ),
        {"rem": new_rem, "st": new_status, "id": int(pass_instance_id)},
    )
    await session.commit()

    detail = await get_trainer_pass_instance_detail(session, trainer_id, pass_instance_id)
    return {
        "pass": detail,
        "booking_id": int(booking_id),
        "already_redeemed": False,
    }

