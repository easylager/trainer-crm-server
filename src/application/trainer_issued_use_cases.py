"""
Trainer-facing timeline of issued passes and certificates (admin «Выданы» tab).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.pass_product_use_cases import SQL_PASS_INSTANCE_SALE_PRICE_CENTS

_PASS_SCOPE_SQL = """
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
)
"""

_PASS_STATUS_LABEL_RU = {
    "active": "Активен",
    "used_up": "Использован",
    "cancelled": "Отменён",
}

_CERT_STATUS_LABEL_RU = {
    "active": "Активен",
    "issued": "Выдан",
    "activated": "Активирован",
    "redeemed": "Погашен",
    "cancelled": "Отменён",
    "expired": "Истёк",
}


def _iso(value: object | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _client_label(name: str | None, client_id: int | None) -> str:
    clean = (name or "").strip()
    if clean and client_id:
        return f"{clean} (#{client_id})"
    if clean:
        return clean
    if client_id:
        return f"Клиент #{client_id}"
    return "—"


def _pass_status_bucket(status: str) -> str:
    return "active" if status == "active" else "closed"


def _cert_status_bucket(status: str) -> str:
    return "active" if status in ("active", "issued", "activated") else "closed"


async def list_trainer_issued_items(
    session: AsyncSession,
    trainer_id: int,
    *,
    kind: str = "all",
    status: str = "all",
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Merged issued passes + certificates for trainer, newest first.

    kind: all | pass | certificate
    status: all | active | closed
    """
    kind_norm = (kind or "all").strip().lower()
    if kind_norm not in ("all", "pass", "certificate"):
        kind_norm = "all"
    status_norm = (status or "all").strip().lower()
    if status_norm not in ("all", "active", "closed"):
        status_norm = "all"
    q = (search or "").strip()
    lim = max(1, min(int(limit or 20), 50))
    off = max(0, int(offset or 0))

    items: list[dict[str, Any]] = []

    if kind_norm in ("all", "pass"):
        clauses = ["p.trainer_id = :tid"]
        params: dict[str, Any] = {"tid": trainer_id}
        if status_norm == "active":
            clauses.append("pi.status = 'active'")
        elif status_norm == "closed":
            clauses.append("pi.status <> 'active'")
        if q:
            clauses.append(
                """(
                  p.name ILIKE :q
                  OR TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) ILIKE :q
                  OR COALESCE(c.phone, '') ILIKE :q
                )"""
            )
            params["q"] = f"%{q}%"
        where = " AND ".join(clauses)
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
                    p.name AS product_name,
                """ + SQL_PASS_INSTANCE_SALE_PRICE_CENTS + """ AS price_cents,
                {_PASS_SCOPE_SQL} AS scope_label,
                    TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                    c.phone
                FROM pass_instances pi
                JOIN trainer_pass_products p ON p.id = pi.pass_product_id
                JOIN clients c ON c.id = pi.client_id
                WHERE {where}
                ORDER BY pi.issued_at DESC
                """
            ),
            params,
        )
        for row in r.fetchall():
            st = str(row[6] or "")
            rem = int(row[2] or 0)
            total = int(row[3] or 0)
            scope = (row[9] or "").strip() or None
            product_name = (row[7] or "").strip() or "Абонемент"
            client_id = int(row[1]) if row[1] is not None else None
            client_label = _client_label(row[10], client_id)
            bucket = _pass_status_bucket(st)
            items.append(
                {
                    "kind": "pass",
                    "id": int(row[0]),
                    "issued_at": _iso(row[4]),
                    "expires_at": _iso(row[5]),
                    "status": st,
                    "status_bucket": bucket,
                    "status_label_ru": _PASS_STATUS_LABEL_RU.get(st, st),
                    "client_id": client_id,
                    "client_label_ru": client_label,
                    "client_phone": (row[11] or "").strip() or None,
                    "product_name": product_name,
                    "sessions_remaining": rem,
                    "sessions_total": total,
                    "service_scope": scope,
                    "price_cents": int(row[8] or 0),
                    "detail_ru": f"{rem} из {total} занятий"
                    + (f" · {scope}" if scope else " · все услуги"),
                }
            )

    if kind_norm in ("all", "certificate"):
        clauses = ["ci.trainer_id = :tid"]
        params = {"tid": trainer_id}
        if status_norm == "active":
            clauses.append("ci.status IN ('active', 'issued', 'activated')")
        elif status_norm == "closed":
            clauses.append("ci.status NOT IN ('active', 'issued', 'activated')")
        if q:
            clauses.append(
                """(
                  COALESCE(cp.name, '') ILIKE :q
                  OR COALESCE(ci.recipient_name, '') ILIKE :q
                  OR COALESCE(ci.purchased_by_name, '') ILIKE :q
                  OR COALESCE(ci.code, '') ILIKE :q
                  OR TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) ILIKE :q
                  OR COALESCE(c.phone, '') ILIKE :q
                )"""
            )
            params["q"] = f"%{q}%"
        where = " AND ".join(clauses)
        r = await session.execute(
            text(
                f"""
                SELECT
                    ci.id,
                    ci.issued_at,
                    ci.expires_at,
                    ci.status,
                    ci.recipient_name,
                    ci.purchased_by_name,
                    ci.amount_cents,
                    ci.amount_remaining_cents,
                    ci.code,
                    ci.file_url,
                    COALESCE(ci.activated_client_id, ci.client_id) AS client_id,
                    TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                    c.phone,
                    cp.name AS product_name
                FROM certificate_instances ci
                LEFT JOIN clients c ON c.id = COALESCE(ci.activated_client_id, ci.client_id)
                LEFT JOIN trainer_certificate_products cp ON cp.id = ci.certificate_product_id
                WHERE {where}
                ORDER BY ci.issued_at DESC
                """
            ),
            params,
        )
        for row in r.fetchall():
            st = str(row[3] or "")
            amount = int(row[6] or 0)
            remaining = row[7]
            remaining_int = int(remaining) if remaining is not None else None
            product_name = (row[13] or "").strip() or "Сертификат"
            recipient = (row[4] or "").strip() or "—"
            client_id = int(row[10]) if row[10] is not None else None
            client_label = _client_label(row[11], client_id) if client_id else recipient
            if remaining_int is not None:
                balance_line = f"остаток {remaining_int / 100:.2f}".replace(".00", "") + " BYN"
            else:
                balance_line = f"номинал {amount / 100:.2f}".replace(".00", "") + " BYN"
            bucket = _cert_status_bucket(st)
            items.append(
                {
                    "kind": "certificate",
                    "id": int(row[0]),
                    "issued_at": _iso(row[1]),
                    "expires_at": _iso(row[2]),
                    "status": st,
                    "status_bucket": bucket,
                    "status_label_ru": _CERT_STATUS_LABEL_RU.get(st, st),
                    "client_id": client_id,
                    "client_label_ru": client_label,
                    "client_phone": (row[12] or "").strip() or None,
                    "product_name": product_name,
                    "recipient_name": recipient,
                    "purchased_by_name": (row[5] or "").strip() or None,
                    "amount_cents": amount,
                    "amount_remaining_cents": remaining_int,
                    "code": (row[8] or "").strip() or None,
                    "file_url": (row[9] or "").strip() or None,
                    "detail_ru": balance_line + f" · код {row[8]}" if row[8] else balance_line,
                }
            )

    items.sort(key=lambda x: x.get("issued_at") or "", reverse=True)
    total = len(items)
    active_count = sum(
        1
        for it in items
        if (
            it["kind"] == "pass"
            and _pass_status_bucket(it["status"]) == "active"
        )
        or (
            it["kind"] == "certificate"
            and _cert_status_bucket(it["status"]) == "active"
        )
    )
    page_items = items[off : off + lim]

    return {
        "items": page_items,
        "total": total,
        "offset": off,
        "limit": lim,
        "has_more": off + len(page_items) < total,
        "active_count": active_count,
    }
