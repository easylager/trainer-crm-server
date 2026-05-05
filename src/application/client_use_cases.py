"""
Client entity: get-or-create by telegram_id or by phone (trainer-added, no bot yet).
Single source of identity for bookings and requests.
"""
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_phone(phone: str | None) -> str | None:
    """Digits only; empty string becomes None. Used for unique lookup."""
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone.strip())
    return digits if digits else None


async def _repoint_client_fks_for_merge(session: AsyncSession, from_cid: int, to_cid: int) -> None:
    """
    Move rows pointing at ``from_cid`` to ``to_cid`` before deleting a duplicate client stub.
    Dedupes composite uniques where both clients had rows (keep ``to_cid`` side).
    """
    if from_cid == to_cid:
        return
    p = {"fc": from_cid, "tc": to_cid}

    await session.execute(
        text("""
            DELETE FROM trainer_client_roster AS r1
            WHERE r1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM trainer_client_roster AS r2
                WHERE r2.client_id = :tc AND r2.trainer_id = r1.trainer_id
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE trainer_client_roster SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM trainer_client_notes AS n1
            WHERE n1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM trainer_client_notes AS n2
                WHERE n2.client_id = :tc AND n2.trainer_id = n1.trainer_id
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE trainer_client_notes SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM trainer_client_tags AS t1
            WHERE t1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM trainer_client_tags AS t2
                WHERE t2.client_id = :tc AND t2.trainer_id = t1.trainer_id AND t2.tag = t1.tag
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE trainer_client_tags SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE trainer_client_entries SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM training_group_members AS m1
            WHERE m1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM training_group_members AS m2
                WHERE m2.client_id = :tc AND m2.training_group_id = m1.training_group_id
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE training_group_members SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM training_group_join_requests AS j1
            WHERE j1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM training_group_join_requests AS j2
                WHERE j2.client_id = :tc AND j2.training_group_id = j1.training_group_id
                  AND j2.status = j1.status
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE training_group_join_requests SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM group_attendance_prompts AS g1
            WHERE g1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM group_attendance_prompts AS g2
                WHERE g2.client_id = :tc AND g2.slot_id = g1.slot_id
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE group_attendance_prompts SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM bookings AS b1
            WHERE b1.client_id = :fc
              AND b1.status IN ('pending', 'confirmed')
              AND EXISTS (
                SELECT 1 FROM bookings AS b2
                WHERE b2.client_id = :tc AND b2.slot_id = b1.slot_id
                  AND b2.status IN ('pending', 'confirmed')
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE bookings SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE client_requests SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE pass_instances SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE certificate_instances SET client_id = :tc WHERE client_id = :fc"),
        p,
    )
    await session.execute(
        text(
            "UPDATE certificate_instances SET activated_client_id = :tc WHERE activated_client_id = :fc"
        ),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM recurring_client_slots AS r1
            WHERE r1.client_id = :fc
              AND r1.status = 'active'
              AND EXISTS (
                SELECT 1 FROM recurring_client_slots AS r2
                WHERE r2.client_id = :tc AND r2.status = 'active'
                  AND r2.trainer_id = r1.trainer_id
                  AND r2.day_of_week = r1.day_of_week
                  AND r2.start_time = r1.start_time
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE recurring_client_slots SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE client_slot_wait_requests SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("""
            DELETE FROM client_inactive_notifications AS i1
            WHERE i1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM client_inactive_notifications AS i2
                WHERE i2.client_id = :tc AND i2.kind = i1.kind
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE client_inactive_notifications SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    await session.execute(
        text("UPDATE booking_problem_reports SET client_id = :tc WHERE client_id = :fc"),
        p,
    )
    await session.execute(
        text("UPDATE booking_client_no_show SET client_id = :tc WHERE client_id = :fc"),
        p,
    )
    await session.execute(
        text("UPDATE welcome_link_tokens SET client_id = :tc WHERE client_id = :fc"),
        p,
    )


async def _absorb_telegram_stub_into_phone_client_if_needed(
    session: AsyncSession,
    telegram_id: int,
    *,
    phone_norm: str,
    phone_val: str | None,
    first_name_val: str | None,
    last_name_val: str | None,
    vk_user_id: int | None,
    telegram_username_val: str | None,
) -> int | None:
    """
    Telegram-only row (e.g. /start) + trainer row with same phone (telegram NULL) → one canonical client.

    Without this, get_or_create_client updates the stub and hits unique ``phone_normalized``.
    """
    r_stub = await session.execute(
        text("SELECT id, vk_user_id, telegram_username FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row_stub = r_stub.fetchone()
    if not row_stub:
        return None
    stub_id = int(row_stub[0])
    stub_vk = row_stub[1]
    stub_raw_tuname = row_stub[2]
    stub_tuname = (
        (str(stub_raw_tuname).strip()[:64] if stub_raw_tuname else None) or None
    )
    merged_tuname = stub_tuname or telegram_username_val

    r_phone = await session.execute(
        text(
            """
            SELECT id, telegram_id
            FROM clients
            WHERE phone_normalized = :pn
            ORDER BY CASE WHEN telegram_id IS NULL THEN 0 ELSE 1 END, id
            LIMIT 1
            """
        ),
        {"pn": phone_norm},
    )
    row_phone = r_phone.fetchone()
    if not row_phone:
        return None
    phone_row_id = int(row_phone[0])
    phone_row_tg = row_phone[1]
    if phone_row_id == stub_id:
        return None
    if phone_row_tg is not None and int(phone_row_tg) != int(telegram_id):
        return None

    await _repoint_client_fks_for_merge(session, stub_id, phone_row_id)
    await session.execute(text("DELETE FROM clients WHERE id = :sid"), {"sid": stub_id})

    await session.execute(
        text("""
            UPDATE clients SET
              telegram_id = :tid,
              phone = :phone,
              phone_normalized = :pn,
              first_name = :fn,
              last_name = :ln,
              vk_user_id = COALESCE(:vk, vk_user_id),
              telegram_username = COALESCE(:tuname, telegram_username),
              updated_at = now()
            WHERE id = :cid
        """),
        {
            "tid": telegram_id,
            "phone": phone_val,
            "pn": phone_norm,
            "fn": first_name_val,
            "ln": last_name_val,
            "vk": stub_vk,
            "tuname": merged_tuname,
            "cid": phone_row_id,
        },
    )
    return phone_row_id


async def get_or_create_client(
    session: AsyncSession,
    telegram_id: int,
    *,
    vk_user_id: int | None = None,
    phone: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    telegram_username: str | None = None,
) -> int:
    """
    Resolve client by telegram_id (surrogate for MAX catalog) or vk_user_id. Create if missing; optionally update name/phone.
    If telegram row is missing but phone matches an offline row (telegram_id IS NULL), bind Telegram to it.
    Returns client_id. Caller must commit (we do not commit here to allow same transaction as booking/request).
    """
    phone_val = (phone or "").strip()[:32] if phone is not None else None
    if phone_val == "":
        phone_val = None
    phone_norm = normalize_phone(phone_val) if phone_val else None
    first_name_val = (first_name or "").strip()[:64] or None
    last_name_val = (last_name or "").strip()[:64] or None
    telegram_username_val = (telegram_username or "").strip()[:64] or None

    if phone_norm is not None:
        absorbed_id = await _absorb_telegram_stub_into_phone_client_if_needed(
            session,
            telegram_id,
            phone_norm=phone_norm,
            phone_val=phone_val,
            first_name_val=first_name_val,
            last_name_val=last_name_val,
            vk_user_id=vk_user_id,
            telegram_username_val=telegram_username_val,
        )
        if absorbed_id is not None:
            return absorbed_id

    r = await session.execute(
        text("SELECT id, phone, first_name, last_name, telegram_username FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row and vk_user_id is not None:
        r = await session.execute(
            text("SELECT id, phone, first_name, last_name, telegram_username FROM clients WHERE vk_user_id = :vk"),
            {"vk": vk_user_id},
        )
        row = r.fetchone()
    if row:
        client_id = row[0]
        # Optional update: fill or refresh name/phone when provided
        updates = []
        params: dict = {"cid": client_id}
        if phone is not None and phone_val is not None:
            updates.append("phone = :phone")
            params["phone"] = phone_val
            if phone_norm is not None:
                updates.append("phone_normalized = :phone_normalized")
                params["phone_normalized"] = phone_norm
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = first_name_val
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = last_name_val
        if telegram_username is not None:
            updates.append("telegram_username = :telegram_username")
            params["telegram_username"] = telegram_username_val
        if vk_user_id is not None:
            updates.append("vk_user_id = COALESCE(vk_user_id, :vk)")
            params["vk"] = vk_user_id
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id

    if phone_norm is not None:
        # Merge path: trainer-created offline client enters Mini App via public link.
        # Attach telegram_id to the existing phone row to keep bookings/history in one profile.
        r_phone = await session.execute(
            text(
                """
                SELECT id, telegram_id
                FROM clients
                WHERE phone_normalized = :pn
                ORDER BY CASE WHEN telegram_id IS NULL THEN 0 ELSE 1 END, id
                LIMIT 1
                """
            ),
            {"pn": phone_norm},
        )
        row_phone = r_phone.fetchone()
        if row_phone and (row_phone[1] is None or int(row_phone[1]) == int(telegram_id)):
            client_id = int(row_phone[0])
            updates = ["telegram_id = :tid"]
            params = {"cid": client_id, "tid": telegram_id}
            if vk_user_id is not None:
                updates.append("vk_user_id = :vk")
                params["vk"] = vk_user_id
            if phone is not None and phone_val is not None:
                updates.append("phone = :phone")
                params["phone"] = phone_val
                updates.append("phone_normalized = :phone_normalized")
                params["phone_normalized"] = phone_norm
            if first_name is not None:
                updates.append("first_name = :first_name")
                params["first_name"] = first_name_val
            if last_name is not None:
                updates.append("last_name = :last_name")
                params["last_name"] = last_name_val
            if telegram_username is not None:
                updates.append("telegram_username = :telegram_username")
                params["telegram_username"] = telegram_username_val
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
            return client_id

    # Insert new client (with phone_normalized if phone provided)
    r = await session.execute(
        text("""
            INSERT INTO clients (telegram_id, vk_user_id, telegram_username, first_name, last_name, phone, phone_normalized)
            VALUES (:tid, :vk, :tuname, :first_name, :last_name, :phone, :phone_normalized)
            RETURNING id
        """),
        {
            "tid": telegram_id,
            "vk": vk_user_id,
            "tuname": telegram_username_val,
            "first_name": first_name_val,
            "last_name": last_name_val,
            "phone": phone_val,
            "phone_normalized": phone_norm,
        },
    )
    (client_id,) = r.fetchone()
    return client_id


async def apply_certificate_recipient_to_client(
    session: AsyncSession,
    client_id: int,
    recipient_name: str | None,
    recipient_phone: str | None,
) -> None:
    """
    When client opens welcome link, fill their profile from certificate if empty.
    recipient_name: split on first space → first_name, last_name; if no space, all in first_name.
    recipient_phone: set phone (and phone_normalized) only if client.phone is empty.
    Only updates fields that are currently empty; does not overwrite existing data.
    """
    r = await session.execute(
        text("SELECT first_name, last_name, phone FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return
    first_name, last_name, phone = row[0], row[1], row[2]
    updates = []
    params: dict = {"cid": client_id}
    if recipient_name and (recipient_name := recipient_name.strip()):
        parts = recipient_name.split(maxsplit=1)
        if not (first_name and first_name.strip()):
            updates.append("first_name = :first_name")
            params["first_name"] = (parts[0] or "").strip()[:64] or None
        if not (last_name and last_name.strip()) and len(parts) > 1:
            updates.append("last_name = :last_name")
            params["last_name"] = (parts[1] or "").strip()[:64] or None
        elif not (last_name and last_name.strip()) and len(parts) == 1:
            pass  # only first_name set above
    if recipient_phone and (recipient_phone := recipient_phone.strip()[:32]) and not (phone and phone.strip()):
        updates.append("phone = :phone")
        params["phone"] = recipient_phone
        norm = normalize_phone(recipient_phone)
        if norm:
            updates.append("phone_normalized = :phone_normalized")
            params["phone_normalized"] = norm
    if updates:
        await session.execute(
            text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
            params,
        )


async def get_or_create_client_by_phone(
    session: AsyncSession,
    phone: str,
    first_name: str | None = None,
    last_name: str | None = None,
    middle_name: str | None = None,
    is_sandbox: bool = False,
) -> int:
    """
    Resolve client by normalized phone (trainer-added, no telegram_id).
    If found: optionally update first_name/last_name/middle_name; return client_id.
    If not found: create with telegram_id=NULL, phone, phone_normalized, names; return client_id.
    Caller must commit.

    ``is_sandbox`` only applies on creation. We never silently flip sandbox state on an existing
    client to avoid leaking demo identity into a real CRM record (or vice versa).
    """
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        raise ValueError("Phone required (digits)")
    first_name = (first_name or "").strip()[:64] or None
    last_name = (last_name or "").strip()[:64] or None
    middle_name = (middle_name or "").strip()[:64] or None
    r = await session.execute(
        text("""
            SELECT id, first_name, last_name, middle_name FROM clients
            WHERE phone_normalized = :pn
        """),
        {"pn": phone_norm},
    )
    row = r.fetchone()
    if row:
        client_id = row[0]
        updates = []
        params: dict = {"cid": client_id}
        if first_name is not None:
            updates.append("first_name = :first_name")
            params["first_name"] = first_name
        if last_name is not None:
            updates.append("last_name = :last_name")
            params["last_name"] = last_name
        if middle_name is not None:
            updates.append("middle_name = :middle_name")
            params["middle_name"] = middle_name
        if updates:
            await session.execute(
                text("UPDATE clients SET updated_at = now(), " + ", ".join(updates) + " WHERE id = :cid"),
                params,
            )
        return client_id
    # Create: store display phone (original) and normalized for lookup
    phone_display = (phone or "").strip()[:32] or phone_norm[:32]
    r = await session.execute(
        text("""
            INSERT INTO clients (
                telegram_id, first_name, middle_name, last_name, phone, phone_normalized, is_sandbox
            )
            VALUES (NULL, :first_name, :middle_name, :last_name, :phone, :phone_normalized, :is_sandbox)
            RETURNING id
        """),
        {
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "phone": phone_display,
            "phone_normalized": phone_norm,
            "is_sandbox": bool(is_sandbox),
        },
    )
    (client_id,) = r.fetchone()
    return client_id


def sandbox_phone_for_trainer(trainer_id: int) -> str:
    """Deterministic per-trainer phantom phone for sandbox client identity.

    Format ``+37500{trainer_id:07d}`` — uses BY country code with operator prefix ``00`` which
    is not assigned to any real mobile carrier, so collisions with real numbers are impossible.
    """
    return f"+37500{int(trainer_id):07d}"


async def get_or_create_sandbox_client_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    first_name: str | None = None,
    last_name: str | None = None,
) -> int:
    """One sandbox client per trainer: idempotent across retries, isolated from real CRM scope."""
    return await get_or_create_client_by_phone(
        session=session,
        phone=sandbox_phone_for_trainer(trainer_id),
        first_name=(first_name or "Александр"),
        last_name=(last_name or "К."),
        is_sandbox=True,
    )


async def get_client_by_phone(session: AsyncSession, phone: str) -> dict | None:
    """Find client by normalized phone. Returns id, telegram_id, first_name, last_name, phone or None."""
    phone_norm = normalize_phone(phone)
    if not phone_norm:
        return None
    r = await session.execute(
        text("""
            SELECT id, telegram_id, first_name, last_name, phone
            FROM clients WHERE phone_normalized = :pn
        """),
        {"pn": phone_norm},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "telegram_id": row[1],
        "first_name": row[2] or "",
        "last_name": row[3] or "",
        "phone": (row[4] or "").strip(),
    }


async def attach_telegram_id_to_client(
    session: AsyncSession,
    client_id: int,
    telegram_id: int,
    telegram_username: str | None = None,
) -> bool:
    """Attach telegram_id to client (e.g. after phone verification). Returns True if updated."""
    raw_un = (telegram_username or "").strip()[:64]
    un = raw_un if raw_un else None
    if un:
        r = await session.execute(
            text("""
                UPDATE clients SET telegram_id = :tid, telegram_username = :un, updated_at = now()
                WHERE id = :cid AND telegram_id IS NULL
                RETURNING id
            """),
            {"tid": telegram_id, "cid": client_id, "un": un},
        )
    else:
        r = await session.execute(
            text("""
                UPDATE clients SET telegram_id = :tid, updated_at = now()
                WHERE id = :cid AND telegram_id IS NULL
                RETURNING id
            """),
            {"tid": telegram_id, "cid": client_id},
        )
    return r.fetchone() is not None


async def get_client_id_by_telegram_id(session: AsyncSession, telegram_id: int) -> int | None:
    """Return client_id for telegram_id, or None if not found."""
    r = await session.execute(
        text("SELECT id FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return row[0] if row else None


async def get_client_telegram_id(session: AsyncSession, client_id: int) -> int | None:
    """Return telegram_id for client_id, or None if not linked (trainer-added client without Telegram)."""
    r = await session.execute(
        text("SELECT telegram_id FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    row = r.fetchone()
    return int(row[0]) if row and row[0] is not None else None


async def get_client_profile_basic(
    session: AsyncSession,
    telegram_id: int,
) -> dict | None:
    """
    Basic client profile for flows: id + first/last name + phone (if any) by telegram_id.
    Used to decide whether to ask for name/phone again in booking/request flows.
    """
    r = await session.execute(
        text("SELECT id, first_name, last_name, phone FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "first_name": row[1] or "",
        "last_name": row[2] or "",
        "phone": (row[3] or "").strip(),
    }


async def get_client_phone_for_webapp(session: AsyncSession, telegram_id: int) -> str | None:
    """
    Phone for Mini App prefill: row linked to telegram_id, or sibling row with same phone_normalized
    (trainer-added duplicate before merge).
    """
    r = await session.execute(
        text("""
            SELECT COALESCE(
                NULLIF(TRIM(COALESCE(c.phone, '')), ''),
                (SELECT TRIM(COALESCE(o.phone, '')) FROM clients o
                 WHERE o.phone_normalized IS NOT NULL
                   AND c.phone_normalized IS NOT NULL
                   AND o.phone_normalized = c.phone_normalized
                   AND o.id IS DISTINCT FROM c.id
                   AND TRIM(COALESCE(o.phone, '')) <> ''
                 LIMIT 1)
            ) AS phone
            FROM clients c
            WHERE c.telegram_id = :tid
            LIMIT 1
        """),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    out = str(row[0]).strip()
    return out or None
