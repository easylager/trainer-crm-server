"""
Client orders a certificate product from their primary trainer via personalized client_requests.
Machine-readable prefix + JSON meta line in comment (no DB migration) — same pattern as pass orders.
"""
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import client_latest_booking_primary_candidate
from src.application.client_request_use_cases import create_client_request
from src.application.client_session_use_cases import get_session as read_client_bot_session
from src.application.client_trainer_edge_use_cases import get_all_edges
from src.application.client_trainer_primary_graph import compute_primary_edge_meta
from src.application.client_use_cases import get_client_id_by_telegram_id
from src.application.certificate_use_cases import get_certificate_product, list_certificate_products
from src.shared.byr_currency_display import BYR_SIGN

CERT_ORDER_LINE_PREFIX = "__CERT_ORDER__:certificate_product_id="
CERT_ORDER_META_PREFIX = "__CERT_ORDER_META__:"

# Client-chosen face value for "any amount" products (BYN → kopeks); sane bounds for abuse prevention.
_CLIENT_CERT_ORDER_MIN_NOMINAL_CENTS = 100  # 1 BYN
_CLIENT_CERT_ORDER_MAX_NOMINAL_CENTS = 50_000_000  # 500k BYN

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def nominal_byn_to_kopeks(byn: float) -> int:
    """Whole currency units (BYN) → integer kopeks, half-up."""
    cents = (Decimal(str(byn)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def split_cert_order_comment(comment: str | None) -> tuple[int | None, dict[str, Any], str]:
    """
    Returns (certificate_product_id_or_none, meta {recipient_email, recipient_name, purchased_by_name?}, human body).
    """
    if not comment or not str(comment).strip():
        return None, {}, ""
    lines = str(comment).strip().split("\n")
    first = lines[0].strip()
    if not first.startswith(CERT_ORDER_LINE_PREFIX):
        return None, {}, str(comment).strip()
    raw_id = first[len(CERT_ORDER_LINE_PREFIX) :].strip()
    try:
        pid = int(raw_id)
    except (TypeError, ValueError):
        return None, {}, str(comment).strip()
    meta: dict[str, Any] = {}
    rest_start = 1
    if len(lines) > 1 and lines[1].strip().startswith(CERT_ORDER_META_PREFIX):
        raw_meta = lines[1].strip()[len(CERT_ORDER_META_PREFIX) :].strip()
        rest_start = 2
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                for k in ("recipient_email", "recipient_name", "purchased_by_name"):
                    v = parsed.get(k)
                    if v is not None and str(v).strip():
                        meta[k] = str(v).strip()
                raw_nom = parsed.get("requested_nominal_cents")
                if raw_nom is not None:
                    try:
                        meta["requested_nominal_cents"] = int(raw_nom)
                    except (TypeError, ValueError):
                        pass
        except (json.JSONDecodeError, TypeError):
            pass
    human = "\n".join(lines[rest_start:]).strip()
    return pid, meta, human if human else str(comment).strip()


def build_certificate_product_order_comment(
    *,
    certificate_product_id: int,
    recipient_email: str,
    recipient_name: str,
    purchased_by_name: str | None,
    human_block: str,
    requested_nominal_cents: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "recipient_email": recipient_email.strip(),
        "recipient_name": recipient_name.strip(),
    }
    pb = (purchased_by_name or "").strip()
    if pb:
        payload["purchased_by_name"] = pb
    if requested_nominal_cents is not None:
        payload["requested_nominal_cents"] = int(requested_nominal_cents)
    meta_line = CERT_ORDER_META_PREFIX + json.dumps(payload, ensure_ascii=False)
    return (
        f"{CERT_ORDER_LINE_PREFIX}{int(certificate_product_id)}\n{meta_line}\n\n{human_block.strip()}"
    )


def is_valid_cert_order_email(email: str) -> bool:
    return bool(email and _EMAIL_RE.match(email.strip()))


async def _trainer_city_and_min_service(
    session: AsyncSession, trainer_id: int
) -> tuple[int | None, int | None]:
    rc = await session.execute(
        text("SELECT city_id FROM trainer_profiles WHERE trainer_id = :tid LIMIT 1"),
        {"tid": trainer_id},
    )
    crow = rc.fetchone()
    city_id = int(crow[0]) if crow and crow[0] is not None else None
    r = await session.execute(
        text("SELECT MIN(service_id)::int FROM trainer_services WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    mrow = r.fetchone()
    sid = int(mrow[0]) if mrow and mrow[0] is not None else None
    return city_id, sid


async def get_primary_cert_order_catalog(session: AsyncSession, telegram_id: int) -> dict:
    """Active certificate products for the client's derived primary trainer (same primary rules as pass-order catalog)."""
    edges = await get_all_edges(telegram_id, session)
    sess_row = await read_client_bot_session(telegram_id, session)
    session_tid = (
        int(sess_row["selected_trainer_id"])
        if sess_row and sess_row.get("selected_trainer_id")
        else None
    )
    book_tid, book_svc = await client_latest_booking_primary_candidate(session, telegram_id)
    primary_edge, _primary_src = compute_primary_edge_meta(
        edges,
        session_tid,
        booking_primary_trainer_id=book_tid,
        booking_primary_service_id=book_svc,
    )
    if not primary_edge:
        return {"trainer_id": None, "trainer_display_name": None, "items": []}

    trainer_id = int(primary_edge["trainer_id"])
    rnm = await session.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(tp.first_name || ' ' || tp.last_name), ''), 'Тренер')
            FROM trainer_profiles tp WHERE tp.trainer_id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    row_nm = rnm.fetchone()
    trainer_display_name = (row_nm[0] or "Тренер").strip() if row_nm else "Тренер"

    items = await list_certificate_products(session, trainer_id, active_only=True)
    if not items:
        return {
            "trainer_id": trainer_id,
            "trainer_display_name": trainer_display_name,
            "items": [],
        }
    return {
        "trainer_id": trainer_id,
        "trainer_display_name": trainer_display_name,
        "items": items,
    }


async def _pending_cert_order_exists(
    session: AsyncSession,
    telegram_id: int,
    trainer_id: int,
    certificate_product_id: int,
) -> bool:
    needle = f"{CERT_ORDER_LINE_PREFIX}{int(certificate_product_id)}"
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


async def _cert_order_sent_today_exists(
    session: AsyncSession,
    telegram_id: int,
    trainer_id: int,
    certificate_product_id: int,
) -> bool:
    needle = f"{CERT_ORDER_LINE_PREFIX}{int(certificate_product_id)}"
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


async def submit_certificate_product_order_request(
    session: AsyncSession,
    *,
    client_id: int,
    telegram_id: int,
    certificate_product_id: int,
    recipient_email: str,
    recipient_name: str,
    nominal_byn: float | None = None,
) -> dict:
    """
    Creates a personalized client_request for the primary trainer.
    Returns {"ok": True, "request_id": int} or {"ok": False, "error": str}.
    """
    resolved = await get_client_id_by_telegram_id(session, int(telegram_id))
    if resolved is None or int(resolved) != int(client_id):
        return {"ok": False, "error": "client_mismatch"}

    if not is_valid_cert_order_email(recipient_email):
        return {"ok": False, "error": "invalid_email"}
    rname = (recipient_name or "").strip()
    if not rname:
        return {"ok": False, "error": "recipient_name_required"}

    edges = await get_all_edges(telegram_id, session)
    sess_row = await read_client_bot_session(telegram_id, session)
    session_tid = (
        int(sess_row["selected_trainer_id"])
        if sess_row and sess_row.get("selected_trainer_id")
        else None
    )
    book_tid, book_svc = await client_latest_booking_primary_candidate(session, telegram_id)
    primary_edge, _primary_src = compute_primary_edge_meta(
        edges,
        session_tid,
        booking_primary_trainer_id=book_tid,
        booking_primary_service_id=book_svc,
    )
    if not primary_edge:
        return {"ok": False, "error": "no_primary_trainer"}

    trainer_id = int(primary_edge["trainer_id"])
    prod = await get_certificate_product(session, certificate_product_id, trainer_id)
    if not prod or not prod.get("is_active"):
        return {"ok": False, "error": "product_not_found"}

    city_id, service_id = await _trainer_city_and_min_service(session, trainer_id)
    if city_id is None:
        return {"ok": False, "error": "trainer_city_missing"}
    if service_id is None:
        return {"ok": False, "error": "trainer_service_missing"}

    if await _pending_cert_order_exists(session, telegram_id, trainer_id, certificate_product_id):
        return {"ok": False, "error": "duplicate_pending"}

    if await _cert_order_sent_today_exists(session, telegram_id, trainer_id, certificate_product_id):
        return {"ok": False, "error": "daily_limit"}

    pname = (prod["name"] or "").strip() or "Подарочный сертификат"
    amt = prod.get("amount_cents")
    requested_nominal_cents: int | None = None
    if amt is None:
        if nominal_byn is None:
            return {"ok": False, "error": "nominal_required"}
        try:
            requested_nominal_cents = nominal_byn_to_kopeks(float(nominal_byn))
        except (ValueError, TypeError, ArithmeticError, InvalidOperation):
            return {"ok": False, "error": "nominal_invalid"}
        if not (
            _CLIENT_CERT_ORDER_MIN_NOMINAL_CENTS
            <= requested_nominal_cents
            <= _CLIENT_CERT_ORDER_MAX_NOMINAL_CENTS
        ):
            return {"ok": False, "error": "nominal_invalid"}
        price_txt = f"{(requested_nominal_cents / 100):.2f}".rstrip("0").rstrip(".")
        amount_line = f"{price_txt} {BYR_SIGN} (номинал по выбору клиента)"
    else:
        price_txt = f"{(int(amt) / 100):.2f}".rstrip("0").rstrip(".")
        amount_line = f"{price_txt} {BYR_SIGN}"

    r_client = await session.execute(
        text(
            """
            SELECT TRIM(CONCAT_WS(' ', NULLIF(TRIM(c.first_name), ''),
              NULLIF(TRIM(c.last_name), '')))
            FROM clients c WHERE c.id = :cid
            """
        ),
        {"cid": client_id},
    )
    crow = r_client.fetchone()
    purchaser = (crow[0] or "").strip() if crow else ""

    human = (
        f'Клиент запрашивает сертификат «{pname}» ({amount_line}).\n'
        f"Получатель: {rname}. Email для отправки PDF: {recipient_email.strip()}.\n"
        "Свяжитесь для оплаты. После оплаты выдайте сертификат: раздел «Сертификаты» → «Выдать сертификат»."
    )
    comment = build_certificate_product_order_comment(
        certificate_product_id=certificate_product_id,
        recipient_email=recipient_email,
        recipient_name=rname,
        purchased_by_name=purchaser or None,
        human_block=human,
        requested_nominal_cents=requested_nominal_cents,
    )
    request_id = await create_client_request(
        session,
        client_id,
        city_id,
        service_id,
        comment=comment,
        trainer_id=trainer_id,
    )
    return {"ok": True, "request_id": request_id}
