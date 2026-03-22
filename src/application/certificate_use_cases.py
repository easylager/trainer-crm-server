"""
Trainer certificate products: fixed amount (e.g. 100 BYN) or "any amount".
Info only — clients see what certificates trainer offers; no platform payment.
Issue: trainer issues certificate instance with code; client redeems with trainer.
"""
import random
import string

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError


async def list_certificate_products(
    session: AsyncSession, trainer_id: int, active_only: bool = False
) -> list[dict]:
    """List certificate products for trainer. Sorted by sort_order, id."""
    q = """
        SELECT id, trainer_id, name, amount_cents, expires_in_days, sort_order, is_active, created_at
        FROM trainer_certificate_products
        WHERE trainer_id = :tid
    """
    if active_only:
        q += " AND is_active = true"
    q += " ORDER BY sort_order, id"
    r = await session.execute(text(q), {"tid": trainer_id})
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "name": row[2],
            "amount_cents": row[3],
            "expires_in_days": row[4],
            "sort_order": row[5],
            "is_active": row[6],
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
        }
        for row in rows
    ]


async def create_certificate_product(
    session: AsyncSession,
    trainer_id: int,
    *,
    name: str,
    amount_cents: int | None,
    sort_order: int = 0,
) -> int:
    """Create certificate product. amount_cents=None means 'any amount'. Returns id."""
    name = (name or "").strip()
    if not name:
        name = "Подарочный сертификат"
    r = await session.execute(
        text("""
            INSERT INTO trainer_certificate_products (trainer_id, name, amount_cents, sort_order)
            VALUES (:tid, :name, :amount_cents, :sort_order)
            RETURNING id
        """),
        {
            "tid": trainer_id,
            "name": name,
            "amount_cents": amount_cents,
            "sort_order": sort_order,
        },
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def get_certificate_product(
    session: AsyncSession, product_id: int, trainer_id: int
) -> dict | None:
    """Get one certificate product by id; must belong to trainer."""
    r = await session.execute(
        text("""
            SELECT id, trainer_id, name, amount_cents, expires_in_days, sort_order, is_active
            FROM trainer_certificate_products
            WHERE id = :id AND trainer_id = :tid
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
        "amount_cents": row[3],
        "expires_in_days": row[4],
        "sort_order": row[5],
        "is_active": row[6],
    }


# Exported for API layer: when PATCH body omits amount_cents, pass this so we don't update the field
AMOUNT_CENTS_UNSET = object()
_UNSET = AMOUNT_CENTS_UNSET


async def update_certificate_product(
    session: AsyncSession,
    product_id: int,
    trainer_id: int,
    *,
    name: str | None = None,
    amount_cents: int | None = _UNSET,  # None = "any amount"; _UNSET = do not change
    expires_in_days: int | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> bool:
    """Update certificate product. amount_cents=None means 'any amount'; _UNSET = do not change. Returns True if updated."""
    updates = []
    params: dict = {"id": product_id, "tid": trainer_id}
    if name is not None:
        name_val = name.strip()
        if not name_val:
            raise ValueError("Name cannot be empty")
        updates.append("name = :name")
        params["name"] = name_val
    if amount_cents is not _UNSET:
        updates.append("amount_cents = :amount_cents")
        params["amount_cents"] = amount_cents
    if expires_in_days is not None:
        updates.append("expires_in_days = :expires_in_days")
        params["expires_in_days"] = expires_in_days
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
        UPDATE trainer_certificate_products
        SET {", ".join(updates)}
        WHERE id = :id AND trainer_id = :tid
    """
    r = await session.execute(text(q), params)
    ok = r.rowcount > 0
    if ok:
        await session.commit()
    return ok


async def delete_certificate_product(
    session: AsyncSession, product_id: int, trainer_id: int
) -> bool:
    """Delete certificate product. Returns True if deleted."""
    r = await session.execute(
        text(
            "DELETE FROM trainer_certificate_products WHERE id = :id AND trainer_id = :tid RETURNING id"
        ),
        {"id": product_id, "tid": trainer_id},
    )
    deleted = r.fetchone() is not None
    if deleted:
        await session.commit()
    return deleted


def _generate_certificate_code() -> str:
    """Unique code for client to present. 10 chars (A-Z,0-9) ~3.7e15 combos — reduces brute-force / guessing risk."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
    return f"CERT-{suffix}"


async def issue_certificate(
    session: AsyncSession,
    trainer_id: int,
    certificate_product_id: int,
    *,
    purchased_by_name: str | None = None,
    recipient_name: str,
    recipient_email: str | None = None,
    recipient_phone: str | None = None,
) -> dict:
    """
    Issue a certificate: create instance with unique code. Product must belong to trainer and be active.
    amount_cents from product (0 if product is "any amount"). Returns instance with code for trainer to send.
    recipient_email: optional; when set, caller can send link by email.
    recipient_phone: optional; stored for welcome-link onboarding (prefill client profile when they open link).
    """
    product = await get_certificate_product(session, certificate_product_id, trainer_id)
    if not product:
        raise ValueError("Certificate product not found or not yours")
    if not product.get("is_active"):
        raise ValueError("Certificate product is inactive")
    # Use product amount; for "any amount" (NULL) store 0
    amount_cents = product["amount_cents"] if product["amount_cents"] is not None else 0
    name = (recipient_name or "").strip() or "—"
    purchaser = (purchased_by_name or "").strip() or None
    email = (recipient_email or "").strip() or None
    phone = (recipient_phone or "").strip()[:32] or None
    expires_at_sql = None
    expires_days = product.get("expires_in_days")
    if isinstance(expires_days, int) and expires_days > 0:
        # Calculated in DB: issued_at + expires_in_days (CURRENT_TIMESTAMP + interval)
        expires_at_sql = f"CURRENT_TIMESTAMP + INTERVAL '{expires_days} days'"
    expires_expr = expires_at_sql or "NULL"
    insert_sql = (
        """
        INSERT INTO certificate_instances
        (trainer_id, certificate_product_id, purchased_by_name, recipient_name, recipient_email, recipient_phone, amount_cents, amount_remaining_cents, code, status, expires_at)
        VALUES (:tid, :pid, :purchased_by_name, :name, :email, :phone, :amount, :amount, :code, 'issued', """
        + expires_expr
        + """
        )
        RETURNING id, trainer_id, certificate_product_id, purchased_by_name, recipient_name, amount_cents, amount_remaining_cents, code, status, issued_at, expires_at
    """
    )
    for _ in range(5):
        code = _generate_certificate_code()
        try:
            r = await session.execute(
                text(insert_sql),
                {
                    "tid": trainer_id,
                    "pid": certificate_product_id,
                    "purchased_by_name": purchaser,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "amount": amount_cents,
                    "code": code,
                },
            )
            row = r.fetchone()
            await session.commit()
            return {
                "id": row[0],
                "trainer_id": row[1],
                "certificate_product_id": row[2],
                "purchased_by_name": row[3],
                "recipient_name": row[4],
                "amount_cents": row[5],
                "code": row[7],
                "status": row[8],
                "issued_at": row[9].isoformat() if hasattr(row[9], "isoformat") else str(row[9]),
                "expires_at": row[10].isoformat() if row[10] and hasattr(row[10], "isoformat") else (str(row[10]) if row[10] else None),
                "recipient_email": email,
            }
        except IntegrityError:
            await session.rollback()
            continue
    raise ValueError("Could not generate unique code, try again")


async def update_certificate_file_url(
    session: AsyncSession, certificate_id: int, trainer_id: int, file_key: str
) -> None:
    """Set file_url (storage key) for certificate after PDF upload."""
    await session.execute(
        text("""
            UPDATE certificate_instances SET file_url = :file_key
            WHERE id = :id AND trainer_id = :tid
        """),
        {"file_key": file_key, "id": certificate_id, "tid": trainer_id},
    )
    await session.commit()


async def get_certificate_file_key(
    session: AsyncSession, certificate_id: int, trainer_id: int
) -> str | None:
    """Return file_url (storage key) for certificate if it belongs to trainer and has file. None otherwise."""
    r = await session.execute(
        text("""
            SELECT file_url FROM certificate_instances
            WHERE id = :id AND trainer_id = :tid AND file_url IS NOT NULL AND file_url != ''
        """),
        {"id": certificate_id, "tid": trainer_id},
    )
    row = r.fetchone()
    return (row[0] or "").strip() or None if row else None


# --- Idempotency (24h TTL) ---
def _idempotency_ttl_hours() -> int:
    return 24


async def get_idempotency_response(
    session: AsyncSession, key: str
) -> dict | None:
    """Return cached response for key if exists and not older than TTL. None otherwise."""
    if not (key or "").strip():
        return None
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_idempotency_ttl_hours())
    r = await session.execute(
        text("""
            SELECT response_json FROM idempotency_keys
            WHERE key = :key AND created_at > :cutoff
        """),
        {"key": key.strip()[:64], "cutoff": cutoff},
    )
    row = r.fetchone()
    if not row:
        return None
    import json
    try:
        val = row[0]
        if val is None:
            return None
        if hasattr(val, "items"):
            return dict(val)
        if isinstance(val, str):
            return json.loads(val)
        return dict(val)
    except Exception:
        return None


async def set_idempotency_response(
    session: AsyncSession, key: str, response: dict
) -> None:
    """Store response for idempotency key (upsert by key)."""
    if not (key or "").strip():
        return
    import json
    k = key.strip()[:64]
    payload = json.dumps(response, default=str)
    await session.execute(
        text("""
            INSERT INTO idempotency_keys (key, response_json, created_at)
            VALUES (:key, CAST(:payload AS jsonb), CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET response_json = EXCLUDED.response_json, created_at = CURRENT_TIMESTAMP
        """),
        {"key": k, "payload": payload},
    )
    await session.commit()


# --- Outbox for failed certificate email ---
async def insert_certificate_email_outbox(
    session: AsyncSession, certificate_id: int, to_email: str
) -> bool:
    """Insert outbox row for later send. Idempotent: no duplicate pending (certificate_id, to_email). Returns True if inserted."""
    to_email = (to_email or "").strip()[:255]
    if not to_email:
        return False
    try:
        await session.execute(
            text("""
                INSERT INTO certificate_email_outbox (certificate_id, to_email, status)
                VALUES (:cid, :email, 'pending')
            """),
            {"cid": certificate_id, "email": to_email},
        )
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False  # already pending for this cert+email


async def get_pending_certificate_email_outbox(
    session: AsyncSession, limit: int = 50
) -> list[dict]:
    """Rows with status=pending for background job. Returns list of {id, certificate_id, to_email}."""
    r = await session.execute(
        text("""
            SELECT id, certificate_id, to_email
            FROM certificate_email_outbox
            WHERE status = 'pending'
            ORDER BY id
            LIMIT :limit
        """),
        {"limit": limit},
    )
    return [{"id": row[0], "certificate_id": row[1], "to_email": row[2]} for row in r.fetchall()]


async def mark_outbox_sent(session: AsyncSession, outbox_id: int) -> None:
    await session.execute(
        text("""
            UPDATE certificate_email_outbox SET status = 'sent', processed_at = CURRENT_TIMESTAMP WHERE id = :id
        """),
        {"id": outbox_id},
    )
    await session.commit()


async def mark_outbox_failed(
    session: AsyncSession, outbox_id: int, error_text: str | None = None
) -> None:
    await session.execute(
        text("""
            UPDATE certificate_email_outbox SET status = 'failed', processed_at = CURRENT_TIMESTAMP, error_text = :err WHERE id = :id
        """),
        {"id": outbox_id, "err": (error_text or "")[:2000]},
    )
    await session.commit()


async def update_certificate_email_sent_at(
    session: AsyncSession, certificate_id: int
) -> None:
    """Set email_sent_at = now() for certificate (after successful send)."""
    await session.execute(
        text("""
            UPDATE certificate_instances SET email_sent_at = CURRENT_TIMESTAMP WHERE id = :id
        """),
        {"id": certificate_id},
    )
    await session.commit()


async def process_certificate_email_outbox_batch(
    session: AsyncSession, limit: int = 20
) -> int:
    """
    Process pending certificate_email_outbox rows: load PDF from storage, send email, mark sent/failed.
    Returns number of processed rows. Call from periodic job.
    """
    from src.infrastructure.s3 import get_file
    from src.shared.email_sender import send_certificate_pdf_email

    pending = await get_pending_certificate_email_outbox(session, limit=limit)
    processed = 0
    for row in pending:
        outbox_id, cert_id, to_email = row["id"], row["certificate_id"], row["to_email"]
        r = await session.execute(
            text("""
                SELECT ci.file_url, ci.code, ci.trainer_id
                FROM certificate_instances ci
                WHERE ci.id = :id AND ci.file_url IS NOT NULL
            """),
            {"id": cert_id},
        )
        cert_row = r.fetchone()
        if not cert_row:
            await mark_outbox_failed(session, outbox_id, "certificate or file_url missing")
            processed += 1
            continue
        file_key, code, trainer_id = cert_row[0], cert_row[1], cert_row[2]
        pdf_result = get_file((file_key or "").strip(), allowed_prefixes=("certificates/",))
        if not pdf_result:
            await mark_outbox_failed(session, outbox_id, "file not found in storage")
            processed += 1
            continue
        pdf_bytes, _ = pdf_result
        # Trainer name for email body
        r2 = await session.execute(
            text("""
                SELECT TRIM(COALESCE(p.first_name, '') || ' ' || COALESCE(p.last_name, ''))
                FROM trainer_profiles p WHERE p.trainer_id = :tid
            """),
            {"tid": trainer_id},
        )
        trainer_name = (r2.fetchone() or (None,))[0] or "Тренер"
        sent = await send_certificate_pdf_email(
            to_email, pdf_bytes, trainer_name=trainer_name, code=(code or "").strip() or "—"
        )
        if sent:
            await mark_outbox_sent(session, outbox_id)
            await update_certificate_email_sent_at(session, cert_id)
        else:
            await mark_outbox_failed(session, outbox_id, "send_certificate_pdf_email returned False")
        processed += 1
    return processed


async def bind_certificate_to_client_by_code(
    session: AsyncSession,
    code: str,
    client_id: int,
) -> dict | None:
    """
    DEPRECATED: old flow (trainer-side redeem). Use activate_certificate_by_code in new model.
    Left for backward compatibility; should not be used in new code.
    """
    code = (code or "").strip()
    if not code:
        return None
    r = await session.execute(
        text("""
            SELECT id, trainer_id, client_id, amount_cents, code, status, recipient_name, recipient_phone
            FROM certificate_instances
            WHERE code = :code AND status = 'active'
        """),
        {"code": code},
    )
    row = r.fetchone()
    if not row:
        return None
    inst_id, trainer_id, existing_cid = row[0], row[1], row[2]
    if existing_cid is not None and existing_cid != client_id:
        return None  # already bound to another client
    if existing_cid != client_id:
        await session.execute(
            text("UPDATE certificate_instances SET client_id = :cid WHERE id = :id"),
            {"cid": client_id, "id": inst_id},
        )
        await session.commit()
    recipient_name = (row[6] or "").strip() or None
    recipient_phone = (row[7] or "").strip() or None
    return {
        "id": inst_id,
        "trainer_id": trainer_id,
        "amount_cents": row[4],
        "code": row[5],
        "recipient_name": recipient_name,
        "recipient_phone": recipient_phone,
    }


async def list_client_certificate_instances(
    session: AsyncSession,
    client_id: int,
) -> list[dict]:
    """
    List certificate instances for a client (where activated_client_id = this client).
    Single query with JOIN on trainer_profiles for trainer name.
    Returns issued/activated; ordered by issued_at DESC.
    """
    r = await session.execute(
        text("""
            SELECT
                ci.id,
                ci.trainer_id,
                ci.amount_cents,
                ci.code,
                ci.status,
                ci.issued_at,
                ci.redeemed_at,
                TRIM(COALESCE(prof.first_name, '') || ' ' || COALESCE(prof.last_name, '')) AS trainer_name
            FROM certificate_instances ci
            LEFT JOIN trainer_profiles prof ON prof.trainer_id = ci.trainer_id
            WHERE ci.activated_client_id = :cid
              AND ci.status IN ('issued', 'activated')
            ORDER BY ci.issued_at DESC
        """),
        {"cid": client_id},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "trainer_id": row[1],
            "amount_cents": row[2],
            "code": row[3],
            "status": row[4],
            "issued_at": row[5].isoformat() if hasattr(row[5], "isoformat") else str(row[5]),
            "redeemed_at": row[6].isoformat() if row[6] and hasattr(row[6], "isoformat") else (str(row[6]) if row[6] else None),
            "trainer_name": (row[7] or "").strip() or "Тренер",
        }
        for row in rows
    ]


async def expire_certificates_past_expiry(session: AsyncSession) -> int:
    """
    Set status = 'expired' for certificate_instances with status in ('issued', 'activated')
    and expires_at < today (inclusive: expire after the expiry date has passed).
    Returns number of rows updated. Call from daily job.
    """
    r = await session.execute(
        text("""
            UPDATE certificate_instances
            SET status = 'expired'
            WHERE status IN ('issued', 'activated')
              AND expires_at IS NOT NULL
              AND (expires_at::date) < CURRENT_DATE
        """),
    )
    await session.commit()
    return r.rowcount if hasattr(r, "rowcount") else 0


async def list_trainer_certificate_instances(
    session: AsyncSession,
    trainer_id: int,
    active_only: bool = False,
) -> list[dict]:
    """
    List certificate instances issued by this trainer (for trainer's "issued certificates" UI).
    active_only: only non-cancelled and non-expired; else all except cancelled.
    Ordered by issued_at DESC. Includes file_url for download link when present.
    """
    q = """
        SELECT id, certificate_product_id, activated_client_id, purchased_by_name, recipient_name,
               amount_cents, code, status, issued_at, redeemed_at, expires_at, file_url
        FROM certificate_instances
        WHERE trainer_id = :tid
    """
    if active_only:
        q += " AND status NOT IN ('cancelled', 'expired')"
    q += " ORDER BY issued_at DESC"
    r = await session.execute(text(q), {"tid": trainer_id})
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "certificate_product_id": row[1],
            "activated_client_id": row[2],
            "purchased_by_name": (row[3] or "").strip() or None,
            "recipient_name": (row[4] or "").strip() or "—",
            "amount_cents": row[5],
            "code": row[6],
            "status": row[7],
            "issued_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
            "redeemed_at": row[9].isoformat() if row[9] and hasattr(row[9], "isoformat") else (str(row[9]) if row[9] else None),
            "expires_at": row[10].isoformat() if row[10] and hasattr(row[10], "isoformat") else (str(row[10]) if row[10] else None),
            "file_url": (row[11] or "").strip() or None,
        }
        for row in rows
    ]


async def list_certificate_instances_for_trainer_client(
    session: AsyncSession,
    trainer_id: int,
    client_id: int,
    active_only: bool = False,
) -> list[dict]:
    """List certificate instances for this client issued by this trainer. For trainer's client card."""
    q = """
        SELECT id, certificate_product_id, activated_client_id, purchased_by_name, recipient_name,
               amount_cents, code, status, issued_at, redeemed_at, expires_at
        FROM certificate_instances
        WHERE trainer_id = :tid AND activated_client_id = :cid
    """
    if active_only:
        q += " AND status NOT IN ('cancelled')"
    q += " ORDER BY issued_at DESC"
    r = await session.execute(text(q), {"tid": trainer_id, "cid": client_id})
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "certificate_product_id": row[1],
            "activated_client_id": row[2],
            "purchased_by_name": (row[3] or "").strip() or None,
            "recipient_name": (row[4] or "").strip() or "—",
            "amount_cents": row[5],
            "code": row[6],
            "status": row[7],
            "issued_at": row[8].isoformat() if hasattr(row[8], "isoformat") else str(row[8]),
            "redeemed_at": row[9].isoformat() if row[9] and hasattr(row[9], "isoformat") else (str(row[9]) if row[9] else None),
            "expires_at": row[10].isoformat() if row[10] and hasattr(row[10], "isoformat") else (str(row[10]) if row[10] else None),
        }
        for row in rows
    ]


async def redeem_certificate_for_booking(
    session: AsyncSession,
    booking_id: int,
) -> bool:
    """
    DEPRECATED in new flow: certificates are activated by client and converted to passes/balance.
    Booking completion should not auto-redeem certificates anymore.
    Kept for backward compatibility; returns False.
    """
    return False


async def redeem_certificate_balance_for_booking(
    session: AsyncSession,
    booking_id: int,
) -> bool:
    """
    Deduct session cost from client's certificate monetary balance for this booking.
    - Finds booking's trainer_id, client_id, service_id.
    - Looks up trainer_services.price_cents for this (trainer, service).
    - Finds oldest certificate for this client+trainer with positive amount_remaining_cents.
    - Decrements amount_remaining_cents by min(remaining, price) (partial coverage allowed).
      If balance becomes zero, marks certificate as 'redeemed'.
    Returns True if any certificate balance was deducted (even partially).
    """
    # 1) Load booking and price for this trainer+service
    r = await session.execute(
        text(
            """
            SELECT b.client_id, b.trainer_id, b.service_id, ts.price_cents
            FROM bookings b
            LEFT JOIN trainer_services ts
              ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
            WHERE b.id = :bid
            """
        ),
        {"bid": booking_id},
    )
    row = r.fetchone()
    if not row:
        return False
    client_id, trainer_id, service_id, price_cents = row
    if client_id is None or trainer_id is None or price_cents is None or price_cents <= 0:
        # No price configured or invalid — nothing to deduct from certificate
        return False

    # 2) Find oldest certificate with remaining balance
    r2 = await session.execute(
        text(
            """
            SELECT id, amount_remaining_cents, status
            FROM certificate_instances
            WHERE activated_client_id = :cid
              AND trainer_id = :tid
              AND (amount_remaining_cents IS NOT NULL AND amount_remaining_cents > 0)
              AND status NOT IN ('cancelled')
            ORDER BY issued_at ASC
            LIMIT 1
            """
        ),
        {"cid": client_id, "tid": trainer_id},
    )
    cert = r2.fetchone()
    if not cert:
        return False
    cert_id, remaining, status = cert
    if remaining is None or remaining <= 0:
        return False

    # Partial deduction: клиент может покрыть занятие частично сертификатом,
    # остаток доплачивается тренеру оффлайн.
    covered = min(remaining, price_cents)
    new_remaining = remaining - covered
    new_status = status
    if new_remaining == 0:
        # mark as redeemed/exhausted (set redeemed_at for stats)
        new_status = "redeemed"

    if new_remaining == 0:
        await session.execute(
            text(
                """
                UPDATE certificate_instances
                SET amount_remaining_cents = 0,
                    status = 'redeemed',
                    redeemed_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {"id": cert_id},
        )
    else:
        await session.execute(
            text(
                """
                UPDATE certificate_instances
                SET amount_remaining_cents = :new_remaining
                WHERE id = :id
                """
            ),
            {"new_remaining": new_remaining, "id": cert_id},
        )
    # Caller controls commit
    return True


async def redeem_certificate(
    session: AsyncSession,
    trainer_id: int,
    *,
    code: str | None = None,
    certificate_instance_id: int | None = None,
) -> dict | None:
    """
    DEPRECATED: manual trainer-side redeem endpoint. New flow relies on client activation and
    pass/balance mechanics. Kept for backward compatibility with existing API routes; should not
    be used in new code paths.
    """
    return None


async def activate_certificate_by_code(
    session: AsyncSession,
    client_id: int,
    code: str,
) -> dict | None:
    """
    New flow: client activates certificate by code.
    - Finds certificate by code and ensures not cancelled/expired (expires_at < now() → None).
    - Sets activated_client_id.
    - Returns basic info including recipient_name/recipient_phone for apply_certificate_recipient_to_client.
    Does NOT create pass/balance here — redeem_certificate_balance_for_booking uses amount_remaining_cents.
    """
    code = (code or "").strip()
    if not code:
        return None
    r = await session.execute(
        text(
            """
            SELECT id, trainer_id, certificate_product_id, status,
                   amount_cents, amount_remaining_cents, issued_at, expires_at,
                   activated_client_id, recipient_name, recipient_phone
            FROM certificate_instances
            WHERE code = :code
            """
        ),
        {"code": code},
    )
    row = r.fetchone()
    if not row:
        return None
    inst_id, trainer_id, product_id, status, amount_cents, amount_remaining_cents, issued_at, expires_at, activated_cid, recipient_name, recipient_phone = row
    # basic guards: cancelled cannot be activated
    if status in ("cancelled",):
        return None
    # expired: do not activate (periodic job sets status=expired separately)
    if expires_at is not None:
        from datetime import datetime, timezone
        try:
            now = datetime.now(timezone.utc)
            # DB may return date or datetime; treat date as "valid until end of that day"
            if hasattr(expires_at, "timestamp"):
                exp_ts = expires_at.timestamp() if expires_at.tzinfo else (expires_at.replace(tzinfo=timezone.utc).timestamp() if hasattr(expires_at, "replace") else 0)
            elif hasattr(expires_at, "year"):
                exp_ts = datetime.combine(expires_at, datetime.max.time(), tzinfo=timezone.utc).timestamp()
            else:
                exp_ts = 0
            if exp_ts < now.timestamp():
                return None
        except Exception:
            pass
    # if already activated by another client, deny; if same client, treat as idempotent
    if activated_cid is not None and activated_cid != client_id:
        return None
    if activated_cid != client_id:
        await session.execute(
            text(
                """
                UPDATE certificate_instances
                SET activated_client_id = :cid,
                    status = CASE WHEN status = 'issued' THEN 'activated' ELSE status END
                WHERE id = :id
                """
            ),
            {"cid": client_id, "id": inst_id},
        )
        await session.commit()
    return {
        "id": inst_id,
        "trainer_id": trainer_id,
        "certificate_product_id": product_id,
        "amount_cents": amount_cents,
        "amount_remaining_cents": amount_remaining_cents,
        "issued_at": issued_at.isoformat() if hasattr(issued_at, "isoformat") else str(issued_at),
        "expires_at": expires_at.isoformat() if expires_at and hasattr(expires_at, "isoformat") else (str(expires_at) if expires_at else None),
        "recipient_name": (recipient_name or "").strip() or None,
        "recipient_phone": (recipient_phone or "").strip()[:32] or None,
    }
