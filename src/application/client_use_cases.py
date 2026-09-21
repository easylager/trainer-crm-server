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

    # client_family_access_members: unique on member_telegram_id alone (not per-primary), so a
    # plain repoint of primary_client_id can never collide with an existing row on the "to" side.
    await session.execute(
        text("UPDATE client_family_access_members SET primary_client_id = :tc WHERE primary_client_id = :fc"),
        p,
    )

    # client_profile_links: unique (account_telegram_id, profile_client_id) — same guardian account
    # could already have a link to the survivor profile.
    await session.execute(
        text("""
            DELETE FROM client_profile_links AS l1
            WHERE l1.profile_client_id = :fc
              AND EXISTS (
                SELECT 1 FROM client_profile_links AS l2
                WHERE l2.profile_client_id = :tc AND l2.account_telegram_id = l1.account_telegram_id
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE client_profile_links SET profile_client_id = :tc WHERE profile_client_id = :fc"),
        p,
    )

    # client_trainer_edges: unique (client_id, trainer_id) — dedupe, then repoint. telegram_id is
    # NOT NULL and denotes the acting account for pushes; re-point it to the survivor's own
    # telegram_id so a merged edge doesn't keep addressing whichever account the stub used to have.
    await session.execute(
        text("""
            DELETE FROM client_trainer_edges AS e1
            WHERE e1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM client_trainer_edges AS e2
                WHERE e2.client_id = :tc AND e2.trainer_id = e1.trainer_id
              )
        """),
        p,
    )
    await session.execute(
        text("""
            UPDATE client_trainer_edges
            SET client_id = :tc,
                telegram_id = COALESCE((SELECT telegram_id FROM clients WHERE id = :tc), telegram_id)
            WHERE client_id = :fc
        """),
        p,
    )

    # client_session_milestone_notifications: unique (client_id, milestone_target) — a milestone
    # already sent from one duplicate must not fire again after merge.
    await session.execute(
        text("""
            DELETE FROM client_session_milestone_notifications AS m1
            WHERE m1.client_id = :fc
              AND EXISTS (
                SELECT 1 FROM client_session_milestone_notifications AS m2
                WHERE m2.client_id = :tc AND m2.milestone_target = m1.milestone_target
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE client_session_milestone_notifications SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    # collective_pass_instances: no unique constraint — a client may legitimately hold several
    # (renewed) passes for the same collective.
    await session.execute(
        text("UPDATE collective_pass_instances SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    # collective_session_bookings: no DB constraint, but an active booking for the same session on
    # both duplicates would double-book one physical seat once merged — dedupe like `bookings`.
    await session.execute(
        text("""
            DELETE FROM collective_session_bookings AS c1
            WHERE c1.client_id = :fc
              AND c1.status IN ('pending', 'confirmed')
              AND EXISTS (
                SELECT 1 FROM collective_session_bookings AS c2
                WHERE c2.client_id = :tc AND c2.collective_session_id = c1.collective_session_id
                  AND c2.status IN ('pending', 'confirmed')
              )
        """),
        p,
    )
    await session.execute(
        text("UPDATE collective_session_bookings SET client_id = :tc WHERE client_id = :fc"),
        p,
    )

    # trainer_client_relay_sessions: no unique constraint — a trainer/client pair can have several
    # relay threads over time (closed + reopened).
    await session.execute(
        text("UPDATE trainer_client_relay_sessions SET client_id = :tc WHERE client_id = :fc"),
        p,
    )


# Every table `_repoint_client_fks_for_merge` moves rows out of, for the pre-merge audit snapshot.
_MERGE_AUDIT_TABLES: tuple[tuple[str, str], ...] = (
    ("trainer_client_roster", "client_id"),
    ("trainer_client_notes", "client_id"),
    ("trainer_client_tags", "client_id"),
    ("trainer_client_entries", "client_id"),
    ("training_group_members", "client_id"),
    ("training_group_join_requests", "client_id"),
    ("group_attendance_prompts", "client_id"),
    ("bookings", "client_id"),
    ("client_requests", "client_id"),
    ("pass_instances", "client_id"),
    ("certificate_instances", "client_id"),
    ("certificate_instances", "activated_client_id"),
    ("recurring_client_slots", "client_id"),
    ("client_slot_wait_requests", "client_id"),
    ("client_inactive_notifications", "client_id"),
    ("booking_problem_reports", "client_id"),
    ("booking_client_no_show", "client_id"),
    ("welcome_link_tokens", "client_id"),
    ("client_family_access_members", "primary_client_id"),
    ("client_profile_links", "profile_client_id"),
    ("client_trainer_edges", "client_id"),
    ("client_session_milestone_notifications", "client_id"),
    ("collective_pass_instances", "client_id"),
    ("collective_session_bookings", "client_id"),
    ("trainer_client_relay_sessions", "client_id"),
)


async def _fetch_client_row_for_merge(session: AsyncSession, client_id: int) -> dict | None:
    r = await session.execute(
        text(
            """
            SELECT id, telegram_id, vk_user_id, telegram_username,
                   first_name, last_name, middle_name, phone, phone_normalized, created_at
            FROM clients WHERE id = :cid
            """
        ),
        {"cid": client_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "telegram_id": row[1],
        "vk_user_id": row[2],
        "telegram_username": row[3],
        "first_name": row[4],
        "last_name": row[5],
        "middle_name": row[6],
        "phone": row[7],
        "phone_normalized": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
    }


async def merge_clients(
    session: AsyncSession,
    from_cid: int,
    to_cid: int,
    *,
    merged_by_trainer_id: int | None = None,
    do_commit: bool = True,
) -> dict:
    """
    Merge duplicate client ``from_cid`` into ``to_cid``: move every FK reference
    (``_repoint_client_fks_for_merge``), regenerate reminders for bookings that moved
    (they were generated, if at all, against the wrong/missing Telegram chat), backfill
    empty name fields on the survivor, record an audit snapshot, then delete the stub.

    ``to_cid`` survives — callers should pass the account with the live Telegram/VK
    identity as ``to_cid`` so the client keeps using the account they actually have open.
    """
    import json

    from src.application.booking_use_cases import generate_reminders_for_booking

    if from_cid == to_cid:
        raise ValueError("merge_clients: from_cid and to_cid must differ")

    from_row = await _fetch_client_row_for_merge(session, from_cid)
    to_row = await _fetch_client_row_for_merge(session, to_cid)
    if from_row is None or to_row is None:
        raise ValueError(f"merge_clients: client not found (from={from_cid}, to={to_cid})")

    moved_counts: dict[str, int] = {}
    for table, column in _MERGE_AUDIT_TABLES:
        r = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :fc"), {"fc": from_cid}
        )
        n = r.scalar_one()
        if n:
            moved_counts[f"{table}.{column}"] = n

    r = await session.execute(
        text("SELECT id FROM bookings WHERE client_id = :fc"), {"fc": from_cid}
    )
    moving_booking_ids = [int(row[0]) for row in r.fetchall()]

    await _repoint_client_fks_for_merge(session, from_cid, to_cid)

    await session.execute(
        text(
            """
            UPDATE clients
            SET first_name = COALESCE(NULLIF(TRIM(first_name), ''), :fn),
                last_name = COALESCE(NULLIF(TRIM(last_name), ''), :ln),
                middle_name = COALESCE(NULLIF(TRIM(middle_name), ''), :mn),
                updated_at = now()
            WHERE id = :tc
            """
        ),
        {
            "fn": from_row["first_name"],
            "ln": from_row["last_name"],
            "mn": from_row["middle_name"],
            "tc": to_cid,
        },
    )

    for bid in moving_booking_ids:
        await generate_reminders_for_booking(session, bid, do_commit=False)

    snapshot = {"from_client": from_row, "to_client": to_row, "moved_counts": moved_counts}
    await session.execute(
        text(
            """
            INSERT INTO client_merges (from_client_id, to_client_id, merged_by_trainer_id, snapshot)
            VALUES (:fc, :tc, :tid, CAST(:snap AS JSONB))
            """
        ),
        {"fc": from_cid, "tc": to_cid, "tid": merged_by_trainer_id, "snap": json.dumps(snapshot)},
    )

    await session.execute(text("DELETE FROM clients WHERE id = :fc"), {"fc": from_cid})

    if do_commit:
        await session.commit()

    return snapshot


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
              first_name = COALESCE(NULLIF(TRIM(first_name), ''), :fn),
              last_name = COALESCE(NULLIF(TRIM(last_name), ''), :ln),
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
    ``first_name`` / ``last_name`` only fill empty CRM fields — never overwrite trainer or self-register data.
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

    fam_cid = await get_family_primary_client_id_for_telegram(session, telegram_id)
    if fam_cid is not None:
        if telegram_username is not None and telegram_username_val is not None:
            await session.execute(
                text(
                    """
                    UPDATE client_family_access_members
                    SET telegram_username = :un
                    WHERE member_telegram_id = :tid
                    """
                ),
                {"un": telegram_username_val, "tid": telegram_id},
            )
        return int(fam_cid)

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
        if first_name is not None and first_name_val is not None:
            updates.append(
                "first_name = COALESCE(NULLIF(TRIM(first_name), ''), :first_name)"
            )
            params["first_name"] = first_name_val
        if last_name is not None and last_name_val is not None:
            updates.append(
                "last_name = COALESCE(NULLIF(TRIM(last_name), ''), :last_name)"
            )
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
            if first_name is not None and first_name_val is not None:
                updates.append(
                    "first_name = COALESCE(NULLIF(TRIM(first_name), ''), :first_name)"
                )
                params["first_name"] = first_name_val
            if last_name is not None and last_name_val is not None:
                updates.append(
                    "last_name = COALESCE(NULLIF(TRIM(last_name), ''), :last_name)"
                )
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
    """Return primary ``clients.id`` for this Telegram user (owner row or family member)."""
    r = await session.execute(
        text("SELECT id FROM clients WHERE telegram_id = :tid"),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if row:
        return int(row[0])
    r2 = await session.execute(
        text(
            """
            SELECT primary_client_id FROM client_family_access_members
            WHERE member_telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": telegram_id},
    )
    row2 = r2.fetchone()
    return int(row2[0]) if row2 else None


async def get_family_primary_client_id_for_telegram(
    session: AsyncSession, telegram_id: int
) -> int | None:
    """If ``telegram_id`` is an extra family account, return linked ``clients.id``; else None."""
    r = await session.execute(
        text(
            """
            SELECT primary_client_id FROM client_family_access_members
            WHERE member_telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    return int(row[0]) if row else None

async def trainer_id_belongs_to_telegram(
    session: AsyncSession, trainer_id: int, telegram_id: int
) -> bool:
    """True when this Telegram account is the trainer's own login (hub must not show self as «мой тренер»)."""
    r = await session.execute(
        text("SELECT 1 FROM trainers WHERE id = :tid AND telegram_id = :tg LIMIT 1"),
        {"tid": int(trainer_id), "tg": int(telegram_id)},
    )
    return r.fetchone() is not None


async def reset_orphan_client_miniapp_trainer_pointers(
    session: AsyncSession, telegram_id: int
) -> bool:
    """
    No row in ``clients`` (and not a family member) but catalog still has trainer pointers —
    stale after CRM delete or trainer testing client bot on the same Telegram account.
    Clears edges and selected_trainer_id; keeps city/service for in-progress catalog browse.
    Returns True when cleanup ran.
    """
    cid = await get_client_id_by_telegram_id(session, int(telegram_id))
    if cid is not None:
        return False
    tg = int(telegram_id)
    await session.execute(
        text("""
            UPDATE client_sessions
            SET selected_trainer_id = NULL,
                state = CASE WHEN state = 'trainer_selected' THEN 'service_selected' ELSE state END,
                updated_at = now()
            WHERE telegram_id = :tg
        """),
        {"tg": tg},
    )
    await session.execute(
        text("DELETE FROM client_trainer_edges WHERE telegram_id = :tg"),
        {"tg": tg},
    )
    await session.commit()
    return True


async def get_client_telegram_id(session: AsyncSession, client_id: int) -> int | None:
    """
    Return telegram chat id for pushes / trainer contact for this clients row.

    Prefer the row's own ``telegram_id``. When NULL (guardian/child profile, or a
    trainer-added offline client that has a profile link), fall back to
    ``client_profile_links.account_telegram_id`` so the parent account still gets
    notifications.
    """
    r = await session.execute(
        text("SELECT telegram_id FROM clients WHERE id = :cid"),
        {"cid": client_id},
    )
    row = r.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    from src.application.client_profile_use_cases import get_account_telegram_id_for_profile

    return await get_account_telegram_id_for_profile(session, int(client_id))


async def get_client_profile_basic(
    session: AsyncSession,
    telegram_id: int,
) -> dict | None:
    """
    Basic client profile for flows: id + first/last name + phone (if any) by telegram_id.
    Used to decide whether to ask for name/phone again in booking/request flows.
    Family members read the primary row (child name + primary phone).
    """
    r = await session.execute(
        text(
            """
            SELECT c.id, c.first_name, c.last_name, c.phone
            FROM clients c
            WHERE c.telegram_id = :tid
            LIMIT 1
            """
        ),
        {"tid": telegram_id},
    )
    row = r.fetchone()
    if not row:
        r2 = await session.execute(
            text(
                """
                SELECT c.id, c.first_name, c.last_name, c.phone
                FROM client_family_access_members m
                JOIN clients c ON c.id = m.primary_client_id
                WHERE m.member_telegram_id = :tid
                LIMIT 1
                """
            ),
            {"tid": telegram_id},
        )
        row = r2.fetchone()
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
    Phone for Mini App prefill: primary row linked to this catalog user (owner or family member).
    Includes sibling-row COALESCE for trainer-added duplicate merge.
    """
    cid = await get_client_id_by_telegram_id(session, telegram_id)
    if cid is None:
        return None
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
            WHERE c.id = :cid
            LIMIT 1
        """),
        {"cid": cid},
    )
    row = r.fetchone()
    if not row or row[0] is None:
        return None
    out = str(row[0]).strip()
    return out or None
