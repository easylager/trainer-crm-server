"""
Client orders an active pass product from their primary trainer via personalized client_requests.
Marker line in comment links CRM flows without a DB migration.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_trainer_primary_graph import (
    compute_primary_edge_meta,
    resolve_primary_catalog_service_id,
)
from src.application.booking_use_cases import (
    client_latest_booking_primary_candidate,
    coerce_service_id_and_name_for_trainer_catalog,
)
from src.application.client_request_use_cases import create_client_request
from src.application.client_session_use_cases import get_session as read_client_bot_session
from src.application.client_trainer_edge_use_cases import get_all_edges
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.pass_product_use_cases import (
    enrich_pass_items_with_catalog_reference_prices,
    get_pass_product,
    list_pass_products,
)
from src.shared.byr_currency_display import BYR_SIGN

PASS_ORDER_LINE_PREFIX = "__PASS_ORDER__:pass_product_id="


def split_pass_order_comment(comment: str | None) -> tuple[int | None, str]:
    """Returns (pass_product_id_or_none, human-visible body)."""
    if not comment or not str(comment).strip():
        return None, ""
    lines = str(comment).strip().split("\n")
    first = lines[0].strip()
    if not first.startswith(PASS_ORDER_LINE_PREFIX):
        return None, str(comment).strip()
    raw_id = first[len(PASS_ORDER_LINE_PREFIX) :].strip()
    try:
        pid = int(raw_id)
    except (TypeError, ValueError):
        return None, str(comment).strip()
    rest = "\n".join(lines[1:]).strip()
    return pid, rest if rest else str(comment).strip()


def build_pass_product_order_comment(*, pass_product_id: int, human_block: str) -> str:
    return f"{PASS_ORDER_LINE_PREFIX}{int(pass_product_id)}\n\n{human_block.strip()}"


async def _enrich_pass_products_pricing(session: AsyncSession, trainer_id: int, items: list[dict]) -> None:
    """Mutates items with price_per_session_cents, pass_price_per_session_cents, savings_* (catalog parity)."""
    r = await session.execute(
        text("SELECT service_id, price_cents FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    price_by_service = {row[0]: row[1] for row in r.fetchall() if row[1] is not None}
    default_single = min(price_by_service.values()) if price_by_service else None
    if default_single is None and items:
        pass_rates = [
            int(p["price_cents"]) // int(p["sessions_total"])
            for p in items
            if p.get("sessions_total") and p.get("price_cents")
        ]
        if pass_rates:
            default_single = max(pass_rates)
    enrich_pass_items_with_catalog_reference_prices(
        items,
        price_by_service=price_by_service,
        default_single_reference=default_single,
    )


async def _trainer_city_and_request_service_for_pass(
    session: AsyncSession,
    trainer_id: int,
    restricted_service_ids: list[int],
) -> tuple[int | None, int | None]:
    """Pick client_request.service_id: smallest id among allowed trainer services, or any if unrestricted."""
    rc = await session.execute(
        text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :tid LIMIT 1"),
        {"tid": trainer_id},
    )
    crow = rc.fetchone()
    city_id = int(crow[0]) if crow and crow[0] is not None else None

    sids = sorted({int(x) for x in restricted_service_ids if x is not None})
    if sids:
        r = await session.execute(
            text(
                """
                SELECT MIN(service_id)::int FROM trainer_services
                WHERE trainer_id = :tid AND service_id = ANY(CAST(:sids AS INTEGER[]))
                """
            ),
            {"tid": trainer_id, "sids": sids},
        )
        mrow = r.fetchone()
        sid = int(mrow[0]) if mrow and mrow[0] is not None else None
        if sid is None:
            r = await session.execute(
                text("SELECT MIN(service_id)::int FROM trainer_services WHERE trainer_id = :tid"),
                {"tid": trainer_id},
            )
            mrow2 = r.fetchone()
            sid = int(mrow2[0]) if mrow2 and mrow2[0] is not None else None
        return city_id, sid

    r = await session.execute(
        text("SELECT MIN(service_id)::int FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    mrow = r.fetchone()
    sid = int(mrow[0]) if mrow and mrow[0] is not None else None
    return city_id, sid


async def get_primary_pass_order_catalog(session: AsyncSession, telegram_id: int) -> dict:
    """
    Active pass products for the client's derived primary trainer (same rules as hub).
    Empty trainer_id when no primary or trainer has no active products.
    """
    edges = await get_all_edges(telegram_id, session)
    sess_row = await read_client_bot_session(telegram_id, session)
    session_tid = int(sess_row["selected_trainer_id"]) if sess_row and sess_row.get("selected_trainer_id") else None
    book_tid, book_svc = await client_latest_booking_primary_candidate(session, telegram_id)
    primary_edge, primary_src = compute_primary_edge_meta(
        edges,
        session_tid,
        booking_primary_trainer_id=book_tid,
        booking_primary_service_id=book_svc,
    )
    if not primary_edge:
        return {"trainer_id": None, "trainer_display_name": None, "items": []}

    trainer_id = int(primary_edge["trainer_id"])
    raw_svc = resolve_primary_catalog_service_id(
        primary_edge, primary_src, sess_row.get("selected_service_id") if sess_row else None
    )
    service_id_hint, _svc_name = await coerce_service_id_and_name_for_trainer_catalog(session, trainer_id, raw_svc)

    rnm = await session.execute(
        text("""
            SELECT COALESCE(NULLIF(TRIM(tp.first_name || ' ' || tp.last_name), ''), 'Тренер')
            FROM trainer_profiles tp WHERE tp.trainer_id = :tid
        """),
        {"tid": trainer_id},
    )
    row_nm = rnm.fetchone()
    trainer_display_name = (row_nm[0] or "Тренер").strip() if row_nm else "Тренер"

    items = await list_pass_products(session, trainer_id, active_only=True)
    if not items:
        return {
            "trainer_id": trainer_id,
            "trainer_display_name": trainer_display_name,
            "primary_catalog_service_id": service_id_hint,
            "items": [],
        }

    await _enrich_pass_products_pricing(session, trainer_id, items)
    return {
        "trainer_id": trainer_id,
        "trainer_display_name": trainer_display_name,
        "primary_catalog_service_id": service_id_hint,
        "items": items,
    }


async def _pending_pass_order_exists(
    session: AsyncSession,
    telegram_id: int,
    trainer_id: int,
    pass_product_id: int,
) -> bool:
    needle = f"{PASS_ORDER_LINE_PREFIX}{int(pass_product_id)}"
    cid = await get_client_id_by_telegram_id(session, int(telegram_id))
    if cid is None:
        return False
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
        {"cid": int(cid), "tid": trainer_id, "needle": needle},
    )
    return r.fetchone() is not None


async def _pass_order_sent_today_exists(
    session: AsyncSession,
    telegram_id: int,
    trainer_id: int,
    pass_product_id: int,
) -> bool:
    """Any pass-order request for this product today (calendar day Europe/Minsk), any status."""
    needle = f"{PASS_ORDER_LINE_PREFIX}{int(pass_product_id)}"
    cid = await get_client_id_by_telegram_id(session, int(telegram_id))
    if cid is None:
        return False
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
        {"cid": int(cid), "tid": trainer_id, "needle": needle},
    )
    return r.fetchone() is not None


async def submit_pass_product_order_request(
    session: AsyncSession,
    *,
    client_id: int,
    telegram_id: int,
    pass_product_id: int,
) -> dict:
    """
    Creates a personalized client_request for the primary trainer.
    Returns {"ok": True, "request_id": int} or {"ok": False, "error": str}.
    """
    resolved = await get_client_id_by_telegram_id(session, int(telegram_id))
    if resolved is None or int(resolved) != int(client_id):
        return {"ok": False, "error": "client_mismatch"}

    edges = await get_all_edges(telegram_id, session)
    sess_row = await read_client_bot_session(telegram_id, session)
    session_tid = int(sess_row["selected_trainer_id"]) if sess_row and sess_row.get("selected_trainer_id") else None
    book_tid, book_svc = await client_latest_booking_primary_candidate(session, telegram_id)
    primary_edge, primary_src = compute_primary_edge_meta(
        edges,
        session_tid,
        booking_primary_trainer_id=book_tid,
        booking_primary_service_id=book_svc,
    )
    if not primary_edge:
        return {"ok": False, "error": "no_primary_trainer"}

    trainer_id = int(primary_edge["trainer_id"])

    prod = await get_pass_product(session, pass_product_id, trainer_id)
    if not prod or not prod.get("is_active"):
        return {"ok": False, "error": "product_not_found"}

    pname = (prod["name"] or "").strip() or "Абонемент"
    sessions_total = int(prod["sessions_total"] or 0)
    price_cents = int(prod["price_cents"] or 0)
    restricted = list(prod.get("service_ids") or [])

    city_id, service_id = await _trainer_city_and_request_service_for_pass(session, trainer_id, restricted)
    if city_id is None:
        return {"ok": False, "error": "trainer_city_missing"}
    if service_id is None:
        return {"ok": False, "error": "trainer_service_missing"}

    if await _pending_pass_order_exists(session, telegram_id, trainer_id, pass_product_id):
        return {"ok": False, "error": "duplicate_pending"}

    if await _pass_order_sent_today_exists(session, telegram_id, trainer_id, pass_product_id):
        return {"ok": False, "error": "daily_limit"}

    price_txt = f"{(price_cents / 100):.2f}".rstrip("0").rstrip(".")
    human = (
        f"Клиент запрашивает абонемент «{pname}»: {sessions_total} занятий, {price_txt} {BYR_SIGN}.\n"
        "Свяжитесь для оплаты. После оплаты выдайте абонемент: раздел «Абонементы» → «Выдать абонемент»."
    )
    comment = build_pass_product_order_comment(pass_product_id=pass_product_id, human_block=human)

    request_id = await create_client_request(
        session,
        client_id,
        city_id,
        service_id,
        comment=comment,
        trainer_id=trainer_id,
    )
    return {"ok": True, "request_id": request_id}
