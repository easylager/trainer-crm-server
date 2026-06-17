"""
Center collective pass products and redemption (ADR-003 W3).

Parallel to trainer_pass_products — scoped to collective_id, pass_kind lane|coach.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_session_use_cases import (
    ATTENDANCE_COACH_PAIR,
    ATTENDANCE_LANE_OWN_COACH,
    ATTENDANCE_LANE_SELF,
    ATTENDANCE_LANE_WITH_GUEST,
    CENTER_TARIFF_GUEST_SURCHARGE_CENTS,
    COACH_ATTENDANCE_MODES,
    LANE_ATTENDANCE_MODES,
    compute_center_booking_price_cents,
)
from src.application.client_pass_order_use_cases import _trainer_city_and_request_service_for_pass
from src.application.client_request_use_cases import create_client_request
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.collective_use_cases import (
    SCHEDULE_MODE_STUDIO_CENTRAL,
    _assert_collective_owner,
    get_collective_by_slug,
)
from src.shared.byr_currency_display import BYR_SIGN

PASS_KIND_LANE = "lane"
PASS_KIND_COACH = "coach"
PASS_KINDS = (PASS_KIND_LANE, PASS_KIND_COACH)

INSTANCE_STATUS_ACTIVE = "active"
INSTANCE_STATUS_USED_UP = "used_up"
INSTANCE_STATUS_EXPIRED = "expired"
INSTANCE_STATUS_CANCELLED = "cancelled"

# ADR-003 reference tariff card (BYN cents, validity_days None = no expiry)
COLLECTIVE_PASS_ORDER_LINE_PREFIX = "__COLLECTIVE_PASS_ORDER__:collective_pass_product_id="


def split_collective_pass_order_comment(comment: str | None) -> tuple[int | None, str]:
    """Returns (collective_pass_product_id_or_none, human-visible body)."""
    if not comment or not str(comment).strip():
        return None, ""
    lines = str(comment).strip().split("\n")
    first = lines[0].strip()
    if not first.startswith(COLLECTIVE_PASS_ORDER_LINE_PREFIX):
        return None, str(comment).strip()
    raw_id = first[len(COLLECTIVE_PASS_ORDER_LINE_PREFIX) :].strip()
    try:
        pid = int(raw_id)
    except (TypeError, ValueError):
        return None, str(comment).strip()
    rest = "\n".join(lines[1:]).strip()
    return pid, rest if rest else str(comment).strip()


def build_collective_pass_product_order_comment(
    *,
    collective_pass_product_id: int,
    human_block: str,
) -> str:
    return (
        f"{COLLECTIVE_PASS_ORDER_LINE_PREFIX}{int(collective_pass_product_id)}\n\n"
        f"{human_block.strip()}"
    )


REFERENCE_COLLECTIVE_PASS_PRODUCTS: tuple[dict[str, Any], ...] = (
    {"pass_kind": PASS_KIND_LANE, "name": "Дорожка 4 посещения", "sessions_total": 4, "price_cents": 7500, "validity_days": None, "sort_order": 10},
    {"pass_kind": PASS_KIND_LANE, "name": "Дорожка 8 посещений", "sessions_total": 8, "price_cents": 14500, "validity_days": 60, "sort_order": 20},
    {"pass_kind": PASS_KIND_LANE, "name": "Дорожка 16 посещений", "sessions_total": 16, "price_cents": 27500, "validity_days": 90, "sort_order": 30},
    {"pass_kind": PASS_KIND_COACH, "name": "Тренер 4 занятия", "sessions_total": 4, "price_cents": 25500, "validity_days": None, "sort_order": 40},
    {"pass_kind": PASS_KIND_COACH, "name": "Тренер 8 занятий", "sessions_total": 8, "price_cents": 49000, "validity_days": 90, "sort_order": 50},
    {"pass_kind": PASS_KIND_COACH, "name": "Тренер 16 занятий", "sessions_total": 16, "price_cents": 96000, "validity_days": 150, "sort_order": 60},
)


def pass_kind_for_attendance_mode(attendance_mode: str) -> str | None:
    """Which collective pass line covers this booking mode."""
    mode = (attendance_mode or "").strip()
    if mode in LANE_ATTENDANCE_MODES:
        return PASS_KIND_LANE
    if mode in COACH_ATTENDANCE_MODES:
        return PASS_KIND_COACH
    return None


def pass_credits_for_attendance_mode(attendance_mode: str) -> int:
    """Coach-credits debited from pass (lane always 1 visit)."""
    mode = (attendance_mode or "").strip()
    if mode == ATTENDANCE_COACH_PAIR:
        return 2
    if mode in LANE_ATTENDANCE_MODES or mode in COACH_ATTENDANCE_MODES:
        return 1
    raise ValueError("invalid_attendance_mode")


def compute_center_booking_price_with_pass(
    attendance_mode: str,
    *,
    guest_count: int = 0,
    using_pass: bool = False,
    pass_kind: str | None = None,
) -> int:
    """
    Amount due on site (PAYG add-ons only when pass covers base visit).

    Lane pass: guest +15 BYN per guest still cash. Coach pass: 0 cash when fully covered.
    """
    mode = (attendance_mode or "").strip()
    guests = max(0, int(guest_count))
    if not using_pass or not pass_kind:
        return compute_center_booking_price_cents(mode, guest_count=guests)

    kind = (pass_kind or "").strip()
    if kind == PASS_KIND_LANE:
        if mode == ATTENDANCE_LANE_WITH_GUEST:
            return guests * CENTER_TARIFF_GUEST_SURCHARGE_CENTS
        if mode == ATTENDANCE_LANE_OWN_COACH and guests > 0:
            return guests * CENTER_TARIFF_GUEST_SURCHARGE_CENTS
        if mode == ATTENDANCE_LANE_SELF:
            return 0
        # lane pass cannot cover coach modes — caller must reject cross-redeem
        return compute_center_booking_price_cents(mode, guest_count=guests)
    if kind == PASS_KIND_COACH:
        if mode in COACH_ATTENDANCE_MODES:
            return 0
        return compute_center_booking_price_cents(mode, guest_count=guests)
    return compute_center_booking_price_cents(mode, guest_count=guests)


def _product_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "collective_id": int(row[1]),
        "pass_kind": str(row[2]),
        "name": str(row[3]),
        "sessions_total": int(row[4]),
        "price_cents": int(row[5]),
        "validity_days": int(row[6]) if row[6] is not None else None,
        "is_active": bool(row[7]),
        "sort_order": int(row[8]),
    }


def _instance_row(row: Any, *, product_name: str | None = None, pass_kind: str | None = None) -> dict[str, Any]:
    issued = row[7]
    expires = row[8]
    return {
        "id": int(row[0]),
        "collective_id": int(row[1]),
        "collective_pass_product_id": int(row[2]),
        "client_id": int(row[3]),
        "sessions_total": int(row[4]),
        "sessions_remaining": int(row[5]),
        "price_cents": int(row[6]),
        "issued_at": issued.isoformat() if hasattr(issued, "isoformat") else str(issued),
        "expires_at": expires.isoformat() if expires and hasattr(expires, "isoformat") else (str(expires) if expires else None),
        "status": str(row[9]),
        "product_name": product_name or str(row[10]) if len(row) > 10 and row[10] else None,
        "pass_kind": pass_kind or (str(row[11]) if len(row) > 11 and row[11] else None),
    }


async def _ensure_studio_central(session: AsyncSession, collective_id: int) -> str | None:
    r = await session.execute(
        text("SELECT schedule_mode FROM collectives WHERE id = :id"),
        {"id": int(collective_id)},
    )
    row = r.fetchone()
    if row is None:
        return "collective_not_found"
    if str(row[0]) != SCHEDULE_MODE_STUDIO_CENTRAL:
        return "not_studio_central"
    return None


async def list_collective_pass_products(
    session: AsyncSession,
    *,
    collective_id: int,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    q = """
        SELECT id, collective_id, pass_kind, name, sessions_total, price_cents,
               validity_days, is_active, sort_order
        FROM collective_pass_products
        WHERE collective_id = :cid
    """
    if active_only:
        q += " AND is_active = true"
    q += " ORDER BY sort_order, id"
    r = await session.execute(text(q), {"cid": int(collective_id)})
    return [_product_row(row) for row in r.fetchall()]


async def seed_reference_collective_pass_products(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
) -> dict[str, Any]:
    """Idempotent: inserts reference tariffs if collective has no products yet."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}
    err = await _ensure_studio_central(session, collective_id)
    if err:
        return {"error": err}
    existing = await list_collective_pass_products(session, collective_id=collective_id)
    if existing:
        return {"ok": True, "created": 0, "products": existing}
    created: list[dict[str, Any]] = []
    for tpl in REFERENCE_COLLECTIVE_PASS_PRODUCTS:
        ins = await session.execute(
            text(
                """
                INSERT INTO collective_pass_products (
                    collective_id, pass_kind, name, sessions_total, price_cents,
                    validity_days, is_active, sort_order
                )
                VALUES (:cid, :kind, :name, :total, :price, :validity, true, :sort)
                RETURNING id, collective_id, pass_kind, name, sessions_total, price_cents,
                          validity_days, is_active, sort_order
                """
            ),
            {
                "cid": int(collective_id),
                "kind": tpl["pass_kind"],
                "name": tpl["name"],
                "total": int(tpl["sessions_total"]),
                "price": int(tpl["price_cents"]),
                "validity": tpl.get("validity_days"),
                "sort": int(tpl.get("sort_order") or 0),
            },
        )
        created.append(_product_row(ins.fetchone()))
    await session.commit()
    return {"ok": True, "created": len(created), "products": created}


async def upsert_collective_pass_product(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
    pass_kind: str,
    name: str,
    sessions_total: int,
    price_cents: int,
    validity_days: int | None = None,
    is_active: bool = True,
    sort_order: int = 0,
    product_id: int | None = None,
) -> dict[str, Any]:
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}
    err = await _ensure_studio_central(session, collective_id)
    if err:
        return {"error": err}
    kind = (pass_kind or "").strip()
    if kind not in PASS_KINDS:
        return {"error": "invalid_pass_kind"}
    nm = (name or "").strip()
    if not nm:
        return {"error": "name_required"}
    total = int(sessions_total)
    if total < 1 or total > 500:
        return {"error": "invalid_sessions_total"}
    price = int(price_cents)
    if price < 0:
        return {"error": "invalid_price"}

    if product_id is not None:
        r = await session.execute(
            text(
                """
                UPDATE collective_pass_products
                SET pass_kind = :kind, name = :name, sessions_total = :total,
                    price_cents = :price, validity_days = :validity,
                    is_active = :active, sort_order = :sort, updated_at = NOW()
                WHERE id = :pid AND collective_id = :cid
                RETURNING id, collective_id, pass_kind, name, sessions_total, price_cents,
                          validity_days, is_active, sort_order
                """
            ),
            {
                "pid": int(product_id),
                "cid": int(collective_id),
                "kind": kind,
                "name": nm[:128],
                "total": total,
                "price": price,
                "validity": validity_days,
                "active": bool(is_active),
                "sort": int(sort_order),
            },
        )
        row = r.fetchone()
        if row is None:
            return {"error": "product_not_found"}
    else:
        r = await session.execute(
            text(
                """
                INSERT INTO collective_pass_products (
                    collective_id, pass_kind, name, sessions_total, price_cents,
                    validity_days, is_active, sort_order
                )
                VALUES (:cid, :kind, :name, :total, :price, :validity, :active, :sort)
                RETURNING id, collective_id, pass_kind, name, sessions_total, price_cents,
                          validity_days, is_active, sort_order
                """
            ),
            {
                "cid": int(collective_id),
                "kind": kind,
                "name": nm[:128],
                "total": total,
                "price": price,
                "validity": validity_days,
                "active": bool(is_active),
                "sort": int(sort_order),
            },
        )
        row = r.fetchone()
    await session.commit()
    return _product_row(row)


async def issue_collective_pass_to_client(
    session: AsyncSession,
    *,
    collective_id: int,
    owner_trainer_id: int,
    client_id: int,
    collective_pass_product_id: int,
) -> dict[str, Any]:
    """Issue pass after external payment (same MVP pattern as trainer passes)."""
    owner_err = await _assert_collective_owner(session, collective_id, owner_trainer_id)
    if owner_err:
        return {"error": owner_err}
    err = await _ensure_studio_central(session, collective_id)
    if err:
        return {"error": err}

    r = await session.execute(
        text(
            """
            SELECT id, pass_kind, name, sessions_total, price_cents, validity_days, is_active
            FROM collective_pass_products
            WHERE id = :pid AND collective_id = :cid
            """
        ),
        {"pid": int(collective_pass_product_id), "cid": int(collective_id)},
    )
    prod = r.fetchone()
    if prod is None:
        return {"error": "product_not_found"}
    if not bool(prod[6]):
        return {"error": "product_inactive"}

    r_cl = await session.execute(text("SELECT 1 FROM clients WHERE id = :id"), {"id": int(client_id)})
    if r_cl.fetchone() is None:
        return {"error": "client_not_found"}

    sessions_total = int(prod[3])
    sale_price = int(prod[4])
    validity_days = prod[5]
    now = datetime.now(timezone.utc)
    expires_at = None
    if validity_days is not None:
        expires_at = now + timedelta(days=int(validity_days))

    ins = await session.execute(
        text(
            """
            INSERT INTO collective_pass_instances (
                collective_id, collective_pass_product_id, client_id,
                sessions_total, sessions_remaining, price_cents, issued_at, expires_at, status
            )
            VALUES (:cid, :pid, :clid, :total, :total, :price, :now, :exp, 'active')
            RETURNING id, collective_id, collective_pass_product_id, client_id,
                      sessions_total, sessions_remaining, price_cents, issued_at, expires_at, status
            """
        ),
        {
            "cid": int(collective_id),
            "pid": int(collective_pass_product_id),
            "clid": int(client_id),
            "total": sessions_total,
            "price": sale_price,
            "now": now,
            "exp": expires_at,
        },
    )
    row = ins.fetchone()
    await session.commit()
    out = _instance_row(row, product_name=str(prod[2]), pass_kind=str(prod[1]))
    out["product_name"] = str(prod[2])
    return out


async def list_client_collective_passes(
    session: AsyncSession,
    *,
    client_id: int,
    collective_id: int,
    redeemable_only: bool = False,
) -> list[dict[str, Any]]:
    """Active passes for client at a center (optionally filter expired/empty)."""
    q = """
        SELECT pi.id, pi.collective_id, pi.collective_pass_product_id, pi.client_id,
               pi.sessions_total, pi.sessions_remaining, pi.price_cents,
               pi.issued_at, pi.expires_at, pi.status,
               p.name, p.pass_kind
        FROM collective_pass_instances pi
        INNER JOIN collective_pass_products p ON p.id = pi.collective_pass_product_id
        WHERE pi.client_id = :clid AND pi.collective_id = :cid
    """
    if redeemable_only:
        q += """
          AND pi.status = 'active'
          AND pi.sessions_remaining > 0
          AND (pi.expires_at IS NULL OR pi.expires_at > NOW())
        """
    q += " ORDER BY pi.expires_at ASC NULLS LAST, pi.id"
    r = await session.execute(
        text(q),
        {"clid": int(client_id), "cid": int(collective_id)},
    )
    return [_instance_row(row) for row in r.fetchall()]


async def validate_pass_for_booking(
    session: AsyncSession,
    *,
    collective_pass_instance_id: int,
    client_id: int,
    collective_id: int,
    attendance_mode: str,
    guest_count: int = 0,
) -> dict[str, Any] | None:
    """
    Returns pass snapshot + credits_needed + payg_cents, or dict with error key.
    """
    required_kind = pass_kind_for_attendance_mode(attendance_mode)
    if required_kind is None:
        return {"error": "invalid_attendance_mode"}
    credits = pass_credits_for_attendance_mode(attendance_mode)

    r = await session.execute(
        text(
            """
            SELECT pi.id, pi.client_id, pi.collective_id, pi.sessions_remaining, pi.status,
                   pi.expires_at, p.pass_kind, p.name
            FROM collective_pass_instances pi
            INNER JOIN collective_pass_products p ON p.id = pi.collective_pass_product_id
            WHERE pi.id = :id
            FOR UPDATE OF pi
            """
        ),
        {"id": int(collective_pass_instance_id)},
    )
    row = r.fetchone()
    if row is None:
        return {"error": "pass_not_found"}
    if int(row[1]) != int(client_id):
        return {"error": "pass_not_yours"}
    if int(row[2]) != int(collective_id):
        return {"error": "pass_wrong_collective"}
    if str(row[4]) != INSTANCE_STATUS_ACTIVE:
        return {"error": "pass_not_active"}
    if int(row[3]) < credits:
        return {"error": "pass_insufficient_credits"}
    expires = row[5]
    if expires is not None:
        exp_dt = expires if isinstance(expires, datetime) else datetime.fromisoformat(str(expires))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt <= datetime.now(timezone.utc):
            return {"error": "pass_expired"}
    pass_kind = str(row[6])
    if pass_kind != required_kind:
        return {"error": "pass_kind_mismatch"}

    payg = compute_center_booking_price_with_pass(
        attendance_mode,
        guest_count=guest_count,
        using_pass=True,
        pass_kind=pass_kind,
    )
    return {
        "collective_pass_instance_id": int(row[0]),
        "pass_kind": pass_kind,
        "product_name": str(row[7]),
        "sessions_remaining": int(row[3]),
        "pass_credits_reserved": credits,
        "booking_price_cents": payg,
        "guest_surcharge_cents": payg,
    }


async def _pending_collective_pass_order_exists(
    session: AsyncSession,
    *,
    client_id: int,
    trainer_id: int,
    collective_pass_product_id: int,
) -> bool:
    needle = f"{COLLECTIVE_PASS_ORDER_LINE_PREFIX}{int(collective_pass_product_id)}"
    r = await session.execute(
        text(
            """
            SELECT 1 FROM client_requests r
            WHERE r.client_id = :cid
              AND r.trainer_id = :tid
              AND r.status = 'new'
              AND POSITION(:needle IN COALESCE(r.comment, '')) = 1
            LIMIT 1
            """
        ),
        {"cid": int(client_id), "tid": int(trainer_id), "needle": needle},
    )
    return r.fetchone() is not None


async def _collective_pass_order_sent_today_exists(
    session: AsyncSession,
    *,
    client_id: int,
    trainer_id: int,
    collective_pass_product_id: int,
) -> bool:
    needle = f"{COLLECTIVE_PASS_ORDER_LINE_PREFIX}{int(collective_pass_product_id)}"
    r = await session.execute(
        text(
            """
            SELECT 1 FROM client_requests r
            WHERE r.client_id = :cid
              AND r.trainer_id = :tid
              AND POSITION(:needle IN COALESCE(r.comment, '')) = 1
              AND (r.created_at AT TIME ZONE 'Europe/Minsk')::date
                  = (CURRENT_TIMESTAMP AT TIME ZONE 'Europe/Minsk')::date
            LIMIT 1
            """
        ),
        {"cid": int(client_id), "tid": int(trainer_id), "needle": needle},
    )
    return r.fetchone() is not None


async def submit_collective_pass_product_order_request(
    session: AsyncSession,
    *,
    client_id: int,
    telegram_id: int,
    collective_slug: str,
    collective_pass_product_id: int,
) -> dict[str, Any]:
    """
    Client requests a center pass product; owner receives a personalized client_request.
    Returns {"ok": True, "request_id": int} or {"ok": False, "error": str}.
    """
    resolved = await get_client_id_by_telegram_id(session, int(telegram_id))
    if resolved is None or int(resolved) != int(client_id):
        return {"ok": False, "error": "client_mismatch"}

    slug = (collective_slug or "").strip()
    if not slug:
        return {"ok": False, "error": "collective_not_found"}

    coll = await get_collective_by_slug(session, slug, active_only=True)
    if coll is None:
        return {"ok": False, "error": "collective_not_found"}

    collective_id = int(coll["id"])
    err = await _ensure_studio_central(session, collective_id)
    if err:
        return {"ok": False, "error": err}

    r_own = await session.execute(
        text("SELECT owner_trainer_id FROM collectives WHERE id = :id"),
        {"id": collective_id},
    )
    own_row = r_own.fetchone()
    if own_row is None or own_row[0] is None:
        return {"ok": False, "error": "no_owner"}
    owner_trainer_id = int(own_row[0])

    r_prod = await session.execute(
        text(
            """
            SELECT id, pass_kind, name, sessions_total, price_cents, validity_days, is_active
            FROM collective_pass_products
            WHERE id = :pid AND collective_id = :cid
            """
        ),
        {"pid": int(collective_pass_product_id), "cid": collective_id},
    )
    prod = r_prod.fetchone()
    if prod is None:
        return {"ok": False, "error": "product_not_found"}
    if not bool(prod[6]):
        return {"ok": False, "error": "product_inactive"}

    pname = (str(prod[2]) or "").strip() or "Абонемент"
    pass_kind = str(prod[1])
    sessions_total = int(prod[3])
    price_cents = int(prod[4])
    validity_days = prod[5]

    city_id, service_id = await _trainer_city_and_request_service_for_pass(
        session,
        owner_trainer_id,
        [],
    )
    if city_id is None:
        return {"ok": False, "error": "trainer_city_missing"}
    if service_id is None:
        return {"ok": False, "error": "trainer_service_missing"}

    if await _pending_collective_pass_order_exists(
        session,
        client_id=int(client_id),
        trainer_id=owner_trainer_id,
        collective_pass_product_id=int(collective_pass_product_id),
    ):
        return {"ok": False, "error": "duplicate_pending"}

    if await _collective_pass_order_sent_today_exists(
        session,
        client_id=int(client_id),
        trainer_id=owner_trainer_id,
        collective_pass_product_id=int(collective_pass_product_id),
    ):
        return {"ok": False, "error": "daily_limit"}

    center_name = (coll.get("display_name") or slug).strip() or "Центр"
    kind_label = "дорожку" if pass_kind == PASS_KIND_LANE else "тренера"
    price_txt = f"{(price_cents / 100):.2f}".rstrip("0").rstrip(".")
    validity_txt = (
        f", срок {int(validity_days)} дн."
        if validity_days is not None
        else ", без срока"
    )
    human = (
        f"Клиент запрашивает абонемент центра «{center_name}» — «{pname}» "
        f"({kind_label}): {sessions_total} посещений, {price_txt} {BYR_SIGN}{validity_txt}.\n"
        "Свяжитесь для оплаты. После оплаты выдайте абонемент: «Коллектив» → «Абонементы»."
    )
    comment = build_collective_pass_product_order_comment(
        collective_pass_product_id=int(collective_pass_product_id),
        human_block=human,
    )
    request_id = await create_client_request(
        session,
        int(client_id),
        int(city_id),
        int(service_id),
        comment=comment,
        trainer_id=owner_trainer_id,
    )
    return {"ok": True, "request_id": request_id}


async def redeem_collective_pass_for_session_booking(
    session: AsyncSession,
    *,
    booking_id: int,
) -> bool:
    """Debit reserved credits and write redemption row (idempotent per booking)."""
    r = await session.execute(
        text(
            """
            SELECT id, collective_pass_instance_id, pass_credits_reserved,
                   attendance_mode, guest_count, booking_price_cents, status
            FROM collective_session_bookings
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": int(booking_id)},
    )
    row = r.fetchone()
    if row is None:
        return False
    inst_id = row[1]
    credits = int(row[2] or 0)
    if inst_id is None or credits <= 0:
        return False
    if str(row[6]) not in ("confirmed", "completed"):
        return False

    chk = await session.execute(
        text("SELECT 1 FROM collective_pass_redemptions WHERE collective_session_booking_id = :bid"),
        {"bid": int(booking_id)},
    )
    if chk.fetchone():
        return True

    r_inst = await session.execute(
        text(
            """
            SELECT sessions_remaining, status
            FROM collective_pass_instances
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": int(inst_id)},
    )
    inst = r_inst.fetchone()
    if inst is None or str(inst[1]) != INSTANCE_STATUS_ACTIVE:
        return False
    rem = int(inst[0])
    if rem < credits:
        return False

    new_rem = rem - credits
    new_status = INSTANCE_STATUS_USED_UP if new_rem <= 0 else INSTANCE_STATUS_ACTIVE
    guest_surcharge = int(row[5] or 0)

    await session.execute(
        text(
            """
            UPDATE collective_pass_instances
            SET sessions_remaining = :rem, status = :st
            WHERE id = :id
            """
        ),
        {"rem": new_rem, "st": new_status, "id": int(inst_id)},
    )
    await session.execute(
        text(
            """
            INSERT INTO collective_pass_redemptions (
                collective_pass_instance_id, collective_session_booking_id,
                credits_debited, guest_surcharge_cents
            )
            VALUES (:inst, :bid, :credits, :guest)
            """
        ),
        {
            "inst": int(inst_id),
            "bid": int(booking_id),
            "credits": credits,
            "guest": guest_surcharge,
        },
    )
    return True
