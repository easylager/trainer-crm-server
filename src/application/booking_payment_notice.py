"""
Payment / pass / certificate facts for session Telegram notices and booking cards.

Expected payment class (PASS/CERT/ONE_OFF/NONE) is **not stored** on bookings — it is derived
at read/notify time from:
  - current pass/cert balances;
  - chronological queue of active visits (pending/confirmed, non-cancelled slot);
  - already redeemed pass/cert rows on specific bookings.

Cancel/decline frees a virtual pass slot: later visits may move from ONE_OFF → PASS on the next
API load or reminder send. Already delivered Telegram pushes are historical and are not rewritten.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_problem_use_cases import _booking_looks_one_off

DeductionOutcome = Literal["pass", "cert", "none"]

_UPCOMING_BOOKING_STATUSES = frozenset({"pending", "confirmed"})


@dataclass(frozen=True)
class BookingDeductionSnapshot:
    """Actual ledger state after booking completion (pass_redemptions / certificate_booking_credits)."""

    outcome: DeductionOutcome
    pass_sessions_remaining: int | None = None
    cert_amount_cents: int | None = None
    cert_remaining_cents: int | None = None


@dataclass
class _PassPoolEntry:
    instance_id: int
    scoped_service_ids: set[int]
    unrestricted: bool
    scoped_tier_kinds: set[str]
    tier_unrestricted: bool
    remaining: int


@dataclass
class _UpcomingBookingPayRow:
    booking_id: int
    service_id: int
    service_price_variant_id: int | None
    booking_price_cents: int | None
    has_pass_redemption: bool
    has_cert_credit: bool
    price_tier_kind: str | None = None


async def load_booking_deduction_snapshot(
    session: AsyncSession,
    booking_id: int,
) -> BookingDeductionSnapshot:
    """Return how this completed booking was paid (post-redemption)."""
    r = await session.execute(
        text(
            """
            SELECT pi.sessions_remaining
            FROM pass_redemptions pr
            JOIN pass_instances pi ON pi.id = pr.pass_instance_id
            WHERE pr.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if row:
        rem = row[0]
        return BookingDeductionSnapshot(
            outcome="pass",
            pass_sessions_remaining=int(rem) if rem is not None else None,
        )

    r2 = await session.execute(
        text(
            """
            SELECT cbc.amount_cents, ci.amount_remaining_cents
            FROM certificate_booking_credits cbc
            JOIN certificate_instances ci ON ci.id = cbc.certificate_instance_id
            WHERE cbc.booking_id = :bid
            LIMIT 1
            """
        ),
        {"bid": booking_id},
    )
    row2 = r2.fetchone()
    if row2:
        amt, rem = row2[0], row2[1]
        return BookingDeductionSnapshot(
            outcome="cert",
            cert_amount_cents=int(amt) if amt is not None else None,
            cert_remaining_cents=int(rem) if rem is not None else None,
        )

    return BookingDeductionSnapshot(outcome="none")


def _pass_entry_covers_booking(entry: _PassPoolEntry, service_id: int, tier_kind: str | None) -> bool:
    """Mirror SQL_PASS_PRODUCT_COVERS_BOOKING logic in Python for virtual pool allocation."""
    # service scope
    if not entry.unrestricted and int(service_id) not in entry.scoped_service_ids:
        return False
    # tier scope: tier-restricted pass requires a non-NULL matching tier on the booking
    if not entry.tier_unrestricted:
        if tier_kind is None or tier_kind not in entry.scoped_tier_kinds:
            return False
    return True


def _allocate_pass_for_booking(pool: list[_PassPoolEntry], service_id: int, tier_kind: str | None = None) -> bool:
    """Mirror redeem_pass_session_for_booking pick order on a virtual pool."""
    for entry in pool:
        if entry.remaining <= 0:
            continue
        if not _pass_entry_covers_booking(entry, service_id, tier_kind):
            continue
        entry.remaining -= 1
        return True
    return False


def _fallback_payment_class(
    *,
    service_price_variant_id: int | None,
    booking_price_cents: int | None,
    cert_balance_cents: int,
) -> str:
    if cert_balance_cents > 0:
        return "CERT"
    if _booking_looks_one_off(service_price_variant_id, booking_price_cents):
        return "ONE_OFF"
    return "NONE"


def _allocate_expected_payment_classes(rows: list[_UpcomingBookingPayRow], pool: list[_PassPoolEntry], cert_balance_cents: int) -> dict[int, str]:
    """
    Chronological queue: earliest unredeemed visit consumes pass sessions first, then cert balance.
    Pass allocation mirrors SQL_PASS_PRODUCT_COVERS_BOOKING: service AND tier must both match.
    """
    out: dict[int, str] = {}
    virtual_cert = int(cert_balance_cents)
    for row in rows:
        if row.has_pass_redemption:
            out[row.booking_id] = "PASS"
            continue
        if row.has_cert_credit:
            out[row.booking_id] = "CERT"
            continue
        if _allocate_pass_for_booking(pool, row.service_id, row.price_tier_kind):
            out[row.booking_id] = "PASS"
            continue
        price = int(row.booking_price_cents or 0)
        if virtual_cert > 0 and price > 0:
            covered = min(virtual_cert, price)
            virtual_cert -= covered
            out[row.booking_id] = "CERT"
            continue
        out[row.booking_id] = _fallback_payment_class(
            service_price_variant_id=row.service_price_variant_id,
            booking_price_cents=row.booking_price_cents,
            cert_balance_cents=virtual_cert,
        )
    return out


async def _load_pass_pool_for_client_trainer(
    session: AsyncSession,
    client_id: int,
    trainer_id: int,
) -> list[_PassPoolEntry]:
    r = await session.execute(
        text(
            """
            SELECT
                pi.id,
                pi.sessions_remaining,
                COALESCE(
                    ARRAY_AGG(DISTINCT tps.service_id) FILTER (WHERE tps.service_id IS NOT NULL),
                    ARRAY[]::INTEGER[]
                ) AS scoped_service_ids,
                COALESCE(
                    ARRAY_AGG(DISTINCT tpt.tier_kind) FILTER (WHERE tpt.tier_kind IS NOT NULL),
                    ARRAY[]::TEXT[]
                ) AS scoped_tier_kinds
            FROM pass_instances pi
            JOIN trainer_pass_products p ON p.id = pi.pass_product_id
            LEFT JOIN trainer_pass_product_services tps ON tps.pass_product_id = p.id
            LEFT JOIN trainer_pass_product_tiers tpt ON tpt.pass_product_id = p.id
            WHERE pi.client_id = :cid
              AND p.trainer_id = :tid
              AND pi.status = 'active'
              AND pi.sessions_remaining > 0
              AND (pi.expires_at IS NULL OR pi.expires_at > CURRENT_TIMESTAMP)
            GROUP BY pi.id, pi.sessions_remaining, pi.expires_at
            ORDER BY pi.expires_at ASC NULLS LAST, pi.sessions_remaining ASC
            """
        ),
        {"cid": int(client_id), "tid": int(trainer_id)},
    )
    pool: list[_PassPoolEntry] = []
    for row in r.fetchall():
        scoped_svc = {int(sid) for sid in (row[2] or []) if sid is not None}
        scoped_tiers = {str(k) for k in (row[3] or []) if k is not None}
        pool.append(
            _PassPoolEntry(
                instance_id=int(row[0]),
                scoped_service_ids=scoped_svc,
                unrestricted=not scoped_svc,
                scoped_tier_kinds=scoped_tiers,
                tier_unrestricted=not scoped_tiers,
                remaining=int(row[1]),
            )
        )
    return pool


async def _load_cert_balance_cents_for_client_trainer(
    session: AsyncSession,
    client_id: int,
    trainer_id: int,
) -> int:
    r = await session.execute(
        text(
            """
            SELECT COALESCE(SUM(COALESCE(ci.amount_remaining_cents, ci.amount_cents)), 0)
            FROM certificate_instances ci
            WHERE ci.trainer_id = :tid
              AND (ci.client_id = :cid OR ci.activated_client_id = :cid)
              AND ci.status = 'active'
              AND COALESCE(ci.amount_remaining_cents, ci.amount_cents) > 0
              AND (ci.expires_at IS NULL OR ci.expires_at > CURRENT_TIMESTAMP)
            """
        ),
        {"cid": int(client_id), "tid": int(trainer_id)},
    )
    row = r.fetchone()
    return int(row[0] or 0) if row else 0


async def _load_upcoming_payment_queue_for_client_trainer(
    session: AsyncSession,
    client_id: int,
    trainer_id: int,
) -> list[_UpcomingBookingPayRow]:
    r = await session.execute(
        text(
            """
            SELECT
                b.id,
                b.service_id,
                b.service_price_variant_id,
                COALESCE(b.booking_price_cents, ts.price_cents) AS booking_price_cents,
                EXISTS (SELECT 1 FROM pass_redemptions pr WHERE pr.booking_id = b.id) AS has_pass,
                EXISTS (SELECT 1 FROM certificate_booking_credits cbc WHERE cbc.booking_id = b.id) AS has_cert,
                b.price_tier_kind
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            WHERE b.client_id = :cid
              AND b.trainer_id = :tid
              AND b.status IN ('pending', 'confirmed')
              AND NOT b.is_sandbox
              AND COALESCE(TRIM(LOWER(COALESCE(s.status, ''))), '') <> 'cancelled'
            ORDER BY s.slot_date ASC, s.start_time ASC NULLS LAST, b.id ASC
            """
        ),
        {"cid": int(client_id), "tid": int(trainer_id)},
    )
    return [
        _UpcomingBookingPayRow(
            booking_id=int(row[0]),
            service_id=int(row[1]),
            service_price_variant_id=row[2],
            booking_price_cents=row[3],
            has_pass_redemption=bool(row[4]),
            has_cert_credit=bool(row[5]),
            price_tier_kind=row[6] if row[6] else None,
        )
        for row in r.fetchall()
    ]


async def allocate_expected_payment_classes_for_client_trainer(
    session: AsyncSession,
    client_id: int,
    trainer_id: int,
) -> dict[int, str]:
    """Expected PASS/CERT/ONE_OFF/NONE for all upcoming visits of one client with one trainer."""
    rows = await _load_upcoming_payment_queue_for_client_trainer(session, client_id, trainer_id)
    if not rows:
        return {}
    pool = await _load_pass_pool_for_client_trainer(session, client_id, trainer_id)
    cert_balance = await _load_cert_balance_cents_for_client_trainer(session, client_id, trainer_id)
    return _allocate_expected_payment_classes(rows, pool, cert_balance)


async def classify_booking_expected_payment_class(
    session: AsyncSession,
    booking_id: int,
    trainer_id: int,
) -> str | None:
    """Pre-session payment class with pass/cert queue consistency across future bookings."""
    pc_map = await resolve_bookings_expected_payment_class_map(
        session, [(int(booking_id), int(trainer_id))]
    )
    return pc_map.get(int(booking_id))


async def resolve_bookings_expected_payment_class_map(
    session: AsyncSession,
    booking_trainer_pairs: list[tuple[int, int]],
) -> dict[int, str | None]:
    """Batch-resolve PASS | CERT | ONE_OFF | NONE using chronological pass/cert allocation."""
    unique_pairs = list(dict.fromkeys((int(bid), int(tid)) for bid, tid in booking_trainer_pairs))
    if not unique_pairs:
        return {}

    ids = [bid for bid, _ in unique_pairs]
    r = await session.execute(
        text(
            """
            SELECT b.id, b.client_id, b.trainer_id, LOWER(TRIM(COALESCE(b.status, ''))) AS status,
                   EXISTS (SELECT 1 FROM pass_redemptions pr WHERE pr.booking_id = b.id) AS has_pass,
                   EXISTS (SELECT 1 FROM certificate_booking_credits cbc WHERE cbc.booking_id = b.id) AS has_cert,
                   b.service_price_variant_id,
                   COALESCE(b.booking_price_cents, ts.price_cents) AS booking_price_cents
            FROM bookings b
            LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            WHERE b.id = ANY(CAST(:ids AS INTEGER[]))
            """
        ),
        {"ids": ids},
    )
    booking_rows = {
        int(row[0]): {
            "client_id": int(row[1]),
            "trainer_id": int(row[2]),
            "status": (row[3] or "").strip().lower(),
            "has_pass": bool(row[4]),
            "has_cert": bool(row[5]),
            "service_price_variant_id": row[6],
            "booking_price_cents": row[7],
        }
        for row in r.fetchall()
    }

    out: dict[int, str | None] = {}
    groups: dict[tuple[int, int], list[int]] = {}
    for booking_id, trainer_id in unique_pairs:
        meta = booking_rows.get(booking_id)
        if not meta or meta["trainer_id"] != trainer_id:
            out[booking_id] = None
            continue
        if meta["has_pass"]:
            out[booking_id] = "PASS"
            continue
        if meta["has_cert"]:
            out[booking_id] = "CERT"
            continue
        if meta["status"] not in _UPCOMING_BOOKING_STATUSES:
            out[booking_id] = None
            continue
        key = (meta["client_id"], trainer_id)
        groups.setdefault(key, []).append(booking_id)

    for (client_id, trainer_id), booking_ids in groups.items():
        allocated = await allocate_expected_payment_classes_for_client_trainer(
            session, client_id, trainer_id
        )
        for booking_id in booking_ids:
            out[booking_id] = allocated.get(
                booking_id,
                _fallback_payment_class(
                    service_price_variant_id=booking_rows[booking_id]["service_price_variant_id"],
                    booking_price_cents=booking_rows[booking_id]["booking_price_cents"],
                    cert_balance_cents=0,
                ),
            )
    return out


async def enrich_booking_dicts_with_expected_payment_class(
    session: AsyncSession,
    bookings: list[dict],
    *,
    booking_id_key: str = "id",
    trainer_id_key: str = "trainer_id",
    target_key: str = "expected_payment_class",
) -> None:
    """Mutate booking dicts in place with pre-session payment instrument class."""
    if not bookings:
        return
    pairs = [
        (int(b[booking_id_key]), int(b[trainer_id_key]))
        for b in bookings
        if b.get(booking_id_key) is not None and b.get(trainer_id_key) is not None
    ]
    pc_map = await resolve_bookings_expected_payment_class_map(session, pairs)
    for b in bookings:
        bid = b.get(booking_id_key)
        if bid is None:
            continue
        b[target_key] = pc_map.get(int(bid))
