"""
Client request use cases: create request, list for trainer (matching city+service), respond, list for client with responses.
"""
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.repositories.trainer_repository import (
    TRAINER_SERVICE_DEFAULT_TIER_LABEL,
    _sql_public_catalog_education_predicate,
)
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.price_tier_kind import normalize_price_tier_kind, price_tier_label_ru, sql_order_case_tier_kind


async def _trainer_services_with_prices_batch(
    session: AsyncSession,
    trainer_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """
    Same shape as catalog / TrainerRepository: service_id, service_name, price_cents, price_byn,
    price_byn_min/max, price_tiers (with id for booking).
    """
    if not trainer_ids:
        return {}
    placeholders = ", ".join(f":id{i}" for i in range(len(trainer_ids)))
    params: dict[str, Any] = {f"id{i}": v for i, v in enumerate(trainer_ids)}
    rsv = await session.execute(
        text(
            f"""
            SELECT trainer_id, service_id, price_cents, description, group_price_cents
            FROM trainer_services
            WHERE trainer_id IN ({placeholders})
            ORDER BY trainer_id, service_id
            """
        ),
        params,
    )
    rows = rsv.fetchall()
    if not rows:
        return {tid: [] for tid in trainer_ids}
    all_sids = {r[1] for r in rows}
    service_names_by_id: dict[int, str] = {}
    if all_sids:
        s_placeholders = ", ".join(f":s{i}" for i in range(len(all_sids)))
        s_params = {f"s{i}": v for i, v in enumerate(all_sids)}
        r_sn = await session.execute(
            text(f"SELECT id, name FROM services WHERE id IN ({s_placeholders})"),
            s_params,
        )
        service_names_by_id = {r[0]: (r[1] or "") for r in r_sn.fetchall()}
    tiers_by_tid_sid: dict[tuple[int, int], list[dict[str, Any]]] = {}
    rv = await session.execute(
        text(
            f"""
            SELECT trainer_id, service_id, id, label, price_cents, sort_order, tier_kind
            FROM trainer_service_price_variants
            WHERE trainer_id IN ({placeholders})
            ORDER BY trainer_id, service_id,
              {sql_order_case_tier_kind("tier_kind")},
              sort_order
            """
        ),
        params,
    )
    for row in rv.fetchall():
        t_id, s_id, vid = int(row[0]), int(row[1]), int(row[2])
        lab, pc, so = row[3], int(row[4]), int(row[5])
        tk = normalize_price_tier_kind(row[6]) or "adult"
        tiers_by_tid_sid.setdefault((t_id, s_id), []).append(
            {
                "id": vid,
                "tier_kind": tk,
                "label": lab or price_tier_label_ru(tk) or TRAINER_SERVICE_DEFAULT_TIER_LABEL,
                "price_cents": pc,
                "price_byn": round(pc / 100.0, 2),
                "sort_order": so,
            }
        )
    out: dict[int, list[dict[str, Any]]] = {tid: [] for tid in trainer_ids}
    for row in rows:
        tid, sid, price_cents = row[0], row[1], row[2]
        svc_desc: str | None = None
        if len(row) > 3 and row[3] is not None:
            s = str(row[3]).strip()
            if s:
                svc_desc = s
        pc = int(price_cents) if price_cents is not None else None
        price_byn = round(float(price_cents) / 100.0, 2) if price_cents is not None else None
        sid_int = int(sid) if sid is not None else None
        gpc = int(row[4]) if len(row) > 4 and row[4] is not None else None
        tiers = tiers_by_tid_sid.get((int(tid), int(sid)), [])
        if tiers:
            prices = [t["price_cents"] for t in tiers]
            p_min, p_max = min(prices), max(prices)
            price_byn_min = round(p_min / 100.0, 2)
            price_byn_max = round(p_max / 100.0, 2)
        else:
            price_byn_min = price_byn_max = price_byn
        out.setdefault(tid, []).append(
            {
                "service_id": sid_int,
                "service_name": service_names_by_id.get(sid, "—") if sid is not None else "—",
                "price_cents": pc,
                "price_byn": price_byn,
                "price_byn_min": price_byn_min,
                "price_byn_max": price_byn_max,
                "price_tiers": tiers,
                "description": svc_desc,
                "group_price_cents": gpc,
                "group_price_byn": round(gpc / 100.0, 2) if gpc is not None else None,
            }
        )
    return out


async def _public_education_entries_by_trainer_ids(
    session: AsyncSession,
    trainer_ids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """Catalog-visible education rows per trainer (same visibility as GET /api/public/trainers/{id})."""
    if not trainer_ids:
        return {}
    placeholders = ", ".join(f":e{i}" for i in range(len(trainer_ids)))
    params: dict[str, Any] = {f"e{i}": v for i, v in enumerate(trainer_ids)}
    vis = _sql_public_catalog_education_predicate("e")

    def _normalize_document_photos(raw: Any) -> list[dict[str, str | None]]:
        if raw is None:
            return []
        payload = raw
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(payload, list):
            return []
        out: list[dict[str, str | None]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            file_key = (item.get("file_key") or "").strip()
            file_key_list = (item.get("file_key_list") or "").strip() or None
            if not file_key:
                continue
            out.append({"file_key": file_key, "file_key_list": file_key_list})
        return out

    r = await session.execute(
        text(
            f"""
            SELECT e.trainer_id, e.id, e.education_type, e.institution_name, e.program_or_title, e.degree_level,
                   e.city, e.country, e.start_year, e.end_year, e.is_in_progress, e.document_url, e.document_photos
            FROM trainer_education e
            WHERE e.trainer_id IN ({placeholders})
              AND {vis}
            ORDER BY e.trainer_id, e.updated_at DESC, e.id DESC
            """
        ),
        params,
    )
    out: dict[int, list[dict[str, Any]]] = {int(tid): [] for tid in trainer_ids}
    for row in r.fetchall():
        tid = row[0]
        if tid not in out:
            continue
        out[tid].append(
            {
                "id": row[1],
                "education_type": row[2],
                "institution_name": row[3],
                "program_or_title": row[4],
                "degree_level": row[5],
                "city": row[6],
                "country": row[7],
                "start_year": row[8],
                "end_year": row[9],
                "is_in_progress": bool(row[10]),
                "document_url": row[11],
                "document_photos": _normalize_document_photos(row[12]),
            }
        )
    return out


async def _trainer_arena_catalog_batch(
    session: AsyncSession,
    trainer_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Arena ids + names (parallel, ordered by arena_id) and primary_arena_id — same semantics as catalog trainer card.
    """
    if not trainer_ids:
        return {}
    placeholders = ", ".join(f":an{i}" for i in range(len(trainer_ids)))
    params: dict[str, Any] = {f"an{i}": v for i, v in enumerate(trainer_ids)}
    r_pri = await session.execute(
        text(f"SELECT id, primary_arena_id FROM trainers WHERE id IN ({placeholders})"),
        params,
    )
    primary_by_tid: dict[int, int | None] = {}
    for row in r_pri.fetchall():
        tid = int(row[0])
        primary_by_tid[tid] = int(row[1]) if row[1] is not None else None

    r = await session.execute(
        text(
            f"""
            SELECT ta.trainer_id, ta.arena_id, TRIM(COALESCE(a.name, ''))
            FROM trainer_arenas ta
            INNER JOIN arenas a ON a.id = ta.arena_id
            WHERE ta.trainer_id IN ({placeholders})
            ORDER BY ta.trainer_id, ta.arena_id
            """
        ),
        params,
    )
    out: dict[int, dict[str, Any]] = {
        int(tid): {"arena_ids": [], "arena_names": [], "primary_arena_id": primary_by_tid.get(int(tid))}
        for tid in trainer_ids
    }
    for row in r.fetchall():
        tid = int(row[0])
        aid = int(row[1])
        nm = (row[2] or "").strip() or "—"
        if tid not in out:
            continue
        out[tid]["arena_ids"].append(aid)
        out[tid]["arena_names"].append(nm)
    return out


async def create_client_request(
    session: AsyncSession,
    client_id: int,
    city_id: int,
    service_id: int,
    comment: str | None = None,
    trainer_id: int | None = None,
) -> int:
    """Insert client_requests row. trainer_id = personalized request for that trainer. Returns new id."""
    r = await session.execute(
        text("""
            INSERT INTO client_requests (client_id, city_id, service_id, comment, status, trainer_id)
            VALUES (:cid, :city_id, :sid, :comment, 'new', :trainer_id)
            RETURNING id
        """),
        {
            "cid": client_id,
            "city_id": city_id,
            "sid": service_id,
            "comment": (comment or "").strip() or None,
            "trainer_id": trainer_id,
        },
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def update_client_request_comment(
    session: AsyncSession,
    request_id: int,
    client_telegram_id: int,
    new_comment: str | None,
) -> bool:
    """Update comment of client's request. Returns True if updated."""
    r = await session.execute(
        text("""
            UPDATE client_requests r
            SET comment = :comment
            FROM clients cl
            WHERE r.id = :rid AND r.client_id = cl.id AND cl.telegram_id = :tid
            RETURNING r.id
        """),
        {"rid": request_id, "tid": client_telegram_id, "comment": (new_comment or "").strip() or None},
    )
    if r.fetchone() is None:
        return False
    await session.commit()
    return True


async def delete_client_request(
    session: AsyncSession,
    request_id: int,
    client_telegram_id: int,
) -> bool:
    """Delete client's request (CASCADE removes responses). Returns True if deleted."""
    r = await session.execute(
        text("""
            DELETE FROM client_requests r
            USING clients cl
            WHERE r.id = :rid AND r.client_id = cl.id AND cl.telegram_id = :tid
            RETURNING r.id
        """),
        {"rid": request_id, "tid": client_telegram_id},
    )
    if r.fetchone() is None:
        return False
    await session.commit()
    return True


async def replace_client_request_with_new(
    session: AsyncSession,
    old_request_id: int,
    client_telegram_id: int,
    new_comment: str | None,
) -> int | None:
    """
    Delete old request and create new one with same city/service, new comment.
    Trainers get a new notification (pending request notifier picks it up).
    Returns new request id or None if old request not found / not owned by client.
    """
    r = await session.execute(
        text("""
            SELECT r.client_id, r.city_id, r.service_id, r.trainer_id
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id AND cl.telegram_id = :tid
            WHERE r.id = :rid
        """),
        {"rid": old_request_id, "tid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    client_id, city_id, service_id, old_trainer_id = row
    await session.execute(
        text("DELETE FROM client_requests WHERE id = :rid"),
        {"rid": old_request_id},
    )
    r2 = await session.execute(
        text("""
            INSERT INTO client_requests (client_id, city_id, service_id, comment, status, trainer_id)
            VALUES (:cid, :city_id, :sid, :comment, 'new', :trainer_id)
            RETURNING id
        """),
        {
            "cid": client_id,
            "city_id": city_id,
            "sid": service_id,
            "comment": (new_comment or "").strip() or None,
            "trainer_id": old_trainer_id,
        },
    )
    (new_id,) = r2.fetchone()
    await session.commit()
    return new_id


async def create_request_decline(
    session: AsyncSession,
    client_request_id: int,
    trainer_id: int,
) -> bool:
    """
    Trainer declines request. Hidden from their list; client is not notified.
    Returns True if recorded; False if already responded/declined or request doesn't match.
    """
    # Allow decline for: personalized (r.trainer_id = this trainer) or general (city+service match)
    check = await session.execute(
        text("""
            SELECT r.id FROM client_requests r
            WHERE r.id = :rid AND r.status = 'new'
              AND (
                r.trainer_id = :tid
                OR (r.trainer_id IS NULL
                    AND EXISTS (SELECT 1 FROM trainer_profiles p WHERE p.trainer_id = :tid AND p.city_id = r.city_id)
                    AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = :tid AND ts.service_id = r.service_id))
              )
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    if not check.fetchone():
        return False
    exists = await session.execute(
        text("""
            SELECT 1 FROM client_request_declines
            WHERE client_request_id = :rid AND trainer_id = :tid
        """),
        {"rid": client_request_id, "tid": trainer_id},
    )
    if exists.fetchone():
        return True  # already declined
    exists_resp = await session.execute(
        text("""
            SELECT 1 FROM client_request_responses
            WHERE client_request_id = :rid AND trainer_id = :tid
        """),
        {"rid": client_request_id, "tid": trainer_id},
    )
    if exists_resp.fetchone():
        return False
    await session.execute(
        text("""
            INSERT INTO client_request_declines (client_request_id, trainer_id)
            VALUES (:rid, :tid)
        """),
        {"rid": client_request_id, "tid": trainer_id},
    )
    await session.commit()
    return True


async def list_requests_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 50,
) -> list[dict]:
    """
    Requests visible to this trainer: personalized (r.trainer_id = tid) or general (city+service match).
    Includes both not-yet-responded and already-responded ("in progress"); excludes declined.
    Returns is_personalized, client_id, client_telegram_id for "write to client" and "book client" flows.
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.city_id, r.service_id, r.comment, r.created_at,
                   c.name AS city_name,
                   s.name AS service_name,
                   (r.trainer_id = :tid) AS is_personalized,
                   (SELECT 1 FROM client_request_responses resp
                    WHERE resp.client_request_id = r.id AND resp.trainer_id = :tid) IS NOT NULL AS has_responded,
                   EXISTS (
                       SELECT 1 FROM trainer_pending_request_booking pb
                       WHERE pb.client_request_id = r.id AND pb.trainer_id = :tid
                   ) AS remind_slots_pending,
                   r.client_id,
                   cl.telegram_id AS client_telegram_id,
                   NULLIF(TRIM(cl.telegram_username), '') AS client_telegram_username,
                   COALESCE(TRIM(cl.first_name), '') AS client_first_name,
                   TRIM(cl.last_name) AS client_last_name
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            WHERE r.status = 'new'
              AND NOT EXISTS (SELECT 1 FROM client_request_declines d
                              WHERE d.client_request_id = r.id AND d.trainer_id = :tid)
              AND (
                r.trainer_id = :tid
                OR (r.trainer_id IS NULL
                    AND EXISTS (SELECT 1 FROM trainer_profiles p WHERE p.trainer_id = :tid AND p.city_id = r.city_id)
                    AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = :tid AND ts.service_id = r.service_id))
              )
            ORDER BY (SELECT 1 FROM client_request_responses resp
                      WHERE resp.client_request_id = r.id AND resp.trainer_id = :tid) IS NOT NULL DESC,
                     r.created_at DESC
            LIMIT :lim
        """),
        {"tid": trainer_id, "lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "id": row[0],
            "city_id": row[1],
            "service_id": row[2],
            "comment": row[3],
            "created_at": row[4],
            "city_name": row[5],
            "service_name": row[6],
            "is_personalized": bool(row[7]),
            "has_responded": bool(row[8]),
            "remind_slots_pending": bool(row[9]),
            "client_id": row[10],
            "client_telegram_id": row[11],
            "client_telegram_username": (row[12] or "").strip() or None,
            "client_first_name": (row[13] or "").strip() or None,
            "client_last_name": (row[14] or "").strip() or None,
        }
        for row in rows
    ]


async def count_unanswered_requests_for_trainer(session: AsyncSession, trainer_id: int) -> int:
    """
    Count visible client_requests where the trainer has not yet responded.
    Same visibility rules as list_requests_for_trainer; no row limit (full count).
    """
    r = await session.execute(
        text("""
            SELECT COUNT(*)
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            WHERE r.status = 'new'
              AND NOT EXISTS (SELECT 1 FROM client_request_declines d
                              WHERE d.client_request_id = r.id AND d.trainer_id = :tid)
              AND (
                r.trainer_id = :tid
                OR (r.trainer_id IS NULL
                    AND EXISTS (SELECT 1 FROM trainer_profiles p WHERE p.trainer_id = :tid AND p.city_id = r.city_id)
                    AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = :tid AND ts.service_id = r.service_id))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM client_request_responses resp
                  WHERE resp.client_request_id = r.id AND resp.trainer_id = :tid
              )
        """),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    return int(row[0] or 0) if row else 0


async def get_request_client_for_trainer_booking(
    session: AsyncSession, request_id: int, trainer_id: int
) -> dict | None:
    """
    For trainer "book client" flow: ensure trainer responded to this request and return client_id, service_id.
    Returns { client_id, service_id } or None if request not found / trainer didn't respond / request archived.
    """
    r = await session.execute(
        text("""
            SELECT r.client_id, r.service_id
            FROM client_requests r
            INNER JOIN client_request_responses resp ON resp.client_request_id = r.id AND resp.trainer_id = :tid
            WHERE r.id = :rid AND r.status = 'new'
        """),
        {"rid": request_id, "tid": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {"client_id": row[0], "service_id": row[1]}


async def add_trainer_pending_request_booking(
    session: AsyncSession, trainer_id: int, client_request_id: int
) -> bool:
    """Trainer said "remind me when I have slots". Idempotent: one row per (trainer, request).

    Returns True if a new row was inserted, False if it already existed.
    """
    r = await session.execute(
        text("""
            INSERT INTO trainer_pending_request_booking (trainer_id, client_request_id)
            VALUES (:tid, :rid)
            ON CONFLICT (trainer_id, client_request_id) DO NOTHING
            RETURNING 1
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    was_new = r.fetchone() is not None
    await session.commit()
    return was_new


async def clear_trainer_pending_request_booking(
    session: AsyncSession, trainer_id: int, client_request_id: int
) -> None:
    """Remove pending when trainer has booked the client for this request."""
    await session.execute(
        text("""
            DELETE FROM trainer_pending_request_booking
            WHERE trainer_id = :tid AND client_request_id = :rid
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    await session.commit()



async def get_trainers_pending_request_with_slots(
    session: AsyncSession,
    cooldown_minutes: int = 180,
) -> list[dict]:
    """
    Trainers who have "will book later" pending and at least one available slot (today + 14 days).
    Skip if we sent a reminder in the last cooldown_minutes (last_reminder_sent_at).
    Request: any status except 'archived'.
    Returns: trainer_id, trainer_telegram_id, client_request_id.
    """
    # When cooldown_minutes=0, skip the "last reminder" filter so reminder is sent every time
    # Only slots with start still in the future count as actionable availability (retro openings ignored).
    r = await session.execute(
        text(
            f"""
            SELECT DISTINCT p.trainer_id, t.telegram_id, p.client_request_id
            FROM trainer_pending_request_booking p
            INNER JOIN trainers t ON t.id = p.trainer_id AND t.telegram_id IS NOT NULL
            INNER JOIN client_requests r ON r.id = p.client_request_id AND r.status != 'archived'
            INNER JOIN slots s ON s.trainer_id = p.trainer_id
              AND s.slot_date >= CURRENT_DATE
              AND s.slot_date <= CURRENT_DATE + INTERVAL '14 days'
              AND s.status = 'available'
              AND ((s.slot_date + s.start_time) AT TIME ZONE '{NOTIFICATION_TZ}')
                  > (CURRENT_TIMESTAMP AT TIME ZONE '{NOTIFICATION_TZ}')
            WHERE (
                :cooldown_minutes = 0
                OR p.last_reminder_sent_at IS NULL
                OR p.last_reminder_sent_at < NOW() - (INTERVAL '1 minute' * :cooldown_minutes)
            )
            LIMIT 50
            """
        ),
        {"cooldown_minutes": cooldown_minutes},
    )
    rows = r.fetchall()
    return [
        {"trainer_id": row[0], "trainer_telegram_id": row[1], "client_request_id": row[2]}
        for row in rows
    ]


async def mark_trainer_pending_request_reminder_sent(
    session: AsyncSession, trainer_id: int, client_request_id: int
) -> None:
    """Record that we sent "you have slots" reminder for this pending booking."""
    await session.execute(
        text("""
            UPDATE trainer_pending_request_booking
            SET last_reminder_sent_at = NOW()
            WHERE trainer_id = :tid AND client_request_id = :rid
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    await session.commit()


async def create_request_response(
    session: AsyncSession,
    client_request_id: int,
    trainer_id: int,
    trainer_comment: str | None = None,
) -> int | None:
    """
    Trainer responds to request. Optional trainer_comment shown to client (e.g. when slot appears).
    Returns response id if created; None if request not found, doesn't match, or already responded.
    """
    # Allow response for: personalized (r.trainer_id = this trainer) or general (city+service match)
    check = await session.execute(
        text("""
            SELECT r.id FROM client_requests r
            WHERE r.id = :rid AND r.status = 'new'
              AND (
                r.trainer_id = :tid
                OR (r.trainer_id IS NULL
                    AND EXISTS (SELECT 1 FROM trainer_profiles p WHERE p.trainer_id = :tid AND p.city_id = r.city_id)
                    AND EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = :tid AND ts.service_id = r.service_id))
              )
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    if not check.fetchone():
        return None
    exists = await session.execute(
        text("""
            SELECT id FROM client_request_responses
            WHERE client_request_id = :rid AND trainer_id = :tid
        """),
        {"rid": client_request_id, "tid": trainer_id},
    )
    if exists.fetchone():
        return None
    comment_val = (trainer_comment or "").strip() or None
    r = await session.execute(
        text("""
            INSERT INTO client_request_responses (client_request_id, trainer_id, trainer_comment)
            VALUES (:rid, :tid, :comment)
            RETURNING id
        """),
        {"rid": client_request_id, "tid": trainer_id, "comment": comment_val},
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def archive_client_requests_fulfilled_by_bookings(
    session: AsyncSession,
    client_telegram_id: int,
) -> None:
    """
    If a booking was created without client_request_id (catalog flow), the linked request
    could stay status='new'. Archive when an active booking matches the same client+service
    and either a responding trainer or a personalized request trainer.
    """
    r = await session.execute(
        text("""
            UPDATE client_requests r
            SET status = 'archived'
            WHERE r.status = 'new'
              AND r.client_id = (SELECT id FROM clients WHERE telegram_id = :tid LIMIT 1)
              AND (
                EXISTS (
                  SELECT 1 FROM bookings b
                  INNER JOIN client_request_responses resp
                    ON resp.client_request_id = r.id AND resp.trainer_id = b.trainer_id
                  WHERE b.client_id = r.client_id
                    AND b.service_id = r.service_id
                    AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                )
                OR EXISTS (
                  SELECT 1 FROM bookings b
                  WHERE b.client_id = r.client_id
                    AND b.service_id = r.service_id
                    AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                    AND r.trainer_id IS NOT NULL
                    AND b.trainer_id = r.trainer_id
                )
              )
            RETURNING r.id
        """),
        {"tid": client_telegram_id},
    )
    if r.fetchone() is not None:
        await session.commit()


async def list_my_requests_with_responses(
    session: AsyncSession,
    client_telegram_id: int,
    limit: int = 30,
) -> list[dict]:
    """
    Client's requests with list of responding trainers (id, name, telegram_id for link).
    """
    await archive_client_requests_fulfilled_by_bookings(session, client_telegram_id)
    r = await session.execute(
        text("""
            SELECT r.id, r.city_id, r.service_id, r.comment, r.created_at, r.status,
                   c.name AS city_name, s.name AS service_name
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            WHERE cl.telegram_id = :tid AND r.status != 'archived'
            ORDER BY r.created_at DESC
            LIMIT :lim
        """),
        {"tid": client_telegram_id, "lim": limit},
    )
    requests_rows = r.fetchall()
    out = []
    for row in requests_rows:
        req_id, city_id, service_id, comment, created_at, status, city_name, service_name = row
        resp_r = await session.execute(
            text("""
                SELECT resp.trainer_id, tp.first_name, tp.last_name, t.telegram_id, t.telegram_username, resp.trainer_comment,
                       tp.rating_avg, tp.rating_count, tp.experience_years, tp.description, tp.education, tp.session_duration_minutes,
                       (SELECT ph.file_key FROM trainer_photos ph WHERE ph.trainer_id = resp.trainer_id ORDER BY ph.sort_order NULLS LAST, ph.id LIMIT 1) AS photo_key
                FROM client_request_responses resp
                INNER JOIN trainers t ON t.id = resp.trainer_id
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
                WHERE resp.client_request_id = :rid
                ORDER BY resp.created_at ASC
            """),
            {"rid": req_id},
        )
        resp_rows = resp_r.fetchall()
        trainer_ids = [tr[0] for tr in resp_rows]
        services_by_trainer = await _trainer_services_with_prices_batch(session, trainer_ids)
        edu_by_tid = await _public_education_entries_by_trainer_ids(session, trainer_ids)
        arenas_by_tid = await _trainer_arena_catalog_batch(session, trainer_ids)
        responders = []
        for tr in resp_rows:
            first_name = (tr[1] or "").strip()
            last_name = (tr[2] or "").strip()
            name = f"{first_name} {last_name}".strip() or "Тренер"
            tid = tr[0]
            ar = arenas_by_tid.get(tid) or {}
            responders.append({
                "trainer_id": tid,
                "name": name,
                "telegram_id": tr[3],
                "telegram_username": (tr[4] or "").strip() or None,
                "trainer_comment": (tr[5] or "").strip() or None,
                "rating_avg": float(tr[6]) if tr[6] is not None else None,
                "rating_count": (tr[7] or 0) if tr[7] is not None else 0,
                "experience_years": tr[8],
                "description": (tr[9] or "").strip() or None,
                "education": (tr[10] or "").strip() or None,
                "session_duration_minutes": tr[11],
                "photo_key": tr[12],
                "services": services_by_trainer.get(tid, []),
                "education_entries": edu_by_tid.get(tid, []),
                "arena_names": ar.get("arena_names") or [],
                "arena_ids": ar.get("arena_ids") or [],
                "primary_arena_id": ar.get("primary_arena_id"),
            })
        out.append({
            "id": req_id,
            "city_id": city_id,
            "service_id": service_id,
            "comment": comment,
            "created_at": created_at,
            "status": status,
            "city_name": city_name,
            "service_name": service_name,
            "responses": responders,
        })
    return out


async def get_client_request_for_booking(
    session: AsyncSession,
    request_id: int,
    client_telegram_id: int,
) -> dict | None:
    """
    Single request by id if owned by client (for linking booking from Mini App).
    Returns { "id", "service_id", "responses": [{"trainer_id"}, ...] } or None.
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.service_id
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            WHERE r.id = :rid AND cl.telegram_id = :tid AND r.status != 'archived'
        """),
        {"rid": request_id, "tid": client_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    resp_r = await session.execute(
        text("""
            SELECT trainer_id FROM client_request_responses
            WHERE client_request_id = :rid
        """),
        {"rid": request_id},
    )
    return {
        "id": row[0],
        "service_id": row[1],
        "responses": [{"trainer_id": tr[0]} for tr in resp_r.fetchall()],
    }


# --- Notifications: trainer about new request, client about new response ---


async def get_pending_request_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Pairs (request, trainer) where request is new, not yet notified.
    - Personal (r.trainer_id set): only that trainer gets the row.
    - General (r.trainer_id NULL): all trainers matching city+service.
    Returns list of dicts: request_id, trainer_id, trainer_telegram_id, city_name, service_name, comment,
    client_id, client_telegram_id, client_first_name, client_middle_name, client_last_name.
    """
    r = await session.execute(
        text("""
            (
            SELECT r.id, t.id AS trainer_id, t.telegram_id,
                   c.name AS city_name, s.name AS service_name, r.comment,
                   r.client_id, cl.telegram_id AS client_telegram_id,
                   cl.first_name AS client_first_name,
                   cl.middle_name AS client_middle_name,
                   cl.last_name AS client_last_name
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainers t ON t.id = r.trainer_id AND t.telegram_id IS NOT NULL
            LEFT JOIN client_request_notifications n ON n.client_request_id = r.id AND n.trainer_id = t.id
            WHERE r.status = 'new' AND r.trainer_id IS NOT NULL AND n.id IS NULL
            )
            UNION ALL
            (
            SELECT r.id, t.id AS trainer_id, t.telegram_id,
                   c.name AS city_name, s.name AS service_name, r.comment,
                   r.client_id, cl.telegram_id AS client_telegram_id,
                   cl.first_name AS client_first_name,
                   cl.middle_name AS client_middle_name,
                   cl.last_name AS client_last_name
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainer_profiles p ON p.city_id = r.city_id
            INNER JOIN trainer_services ts ON ts.trainer_id = p.trainer_id AND ts.service_id = r.service_id
            INNER JOIN trainers t ON t.id = p.trainer_id AND t.telegram_id IS NOT NULL
            LEFT JOIN client_request_notifications n ON n.client_request_id = r.id AND n.trainer_id = t.id
            WHERE r.status = 'new' AND r.trainer_id IS NULL AND n.id IS NULL
            )
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "request_id": row[0],
            "trainer_id": row[1],
            "trainer_telegram_id": row[2],
            "city_name": row[3],
            "service_name": row[4],
            "comment": row[5],
            "client_id": row[6],
            "client_telegram_id": row[7],
            "client_first_name": row[8],
            "client_middle_name": row[9],
            "client_last_name": row[10],
        }
        for row in rows
    ]


async def get_client_request_notification_payload_for_trainer(
    session: AsyncSession,
    *,
    trainer_telegram_id: int,
    request_id: int,
) -> dict | None:
    """
    Same shape as get_pending_request_notifications rows, scoped to one request and verifying
    Telegram identity belongs to this trainer — for inline keyboards that reference request_id.
    """
    r = await session.execute(
        text(
            """
            SELECT r.id,
                   t.id AS trainer_id,
                   t.telegram_id AS trainer_telegram_id,
                   c.name AS city_name,
                   s.name AS service_name,
                   r.comment,
                   r.client_id,
                   cl.telegram_id AS client_telegram_id,
                   cl.first_name AS client_first_name,
                   cl.middle_name AS client_middle_name,
                   cl.last_name AS client_last_name
            FROM client_requests r
            INNER JOIN clients cl ON cl.id = r.client_id
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainers t ON t.id = r.trainer_id AND t.telegram_id IS NOT NULL
            WHERE r.id = :rid AND t.telegram_id = :ttid AND r.trainer_id IS NOT NULL AND r.status != 'archived'
            """
        ),
        {"rid": request_id, "ttid": trainer_telegram_id},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "request_id": row[0],
        "trainer_id": row[1],
        "trainer_telegram_id": row[2],
        "city_name": row[3],
        "service_name": row[4],
        "comment": row[5],
        "client_id": row[6],
        "client_telegram_id": row[7],
        "client_first_name": row[8],
        "client_middle_name": row[9],
        "client_last_name": row[10],
    }


async def mark_request_trainer_notified(
    session: AsyncSession, request_id: int, trainer_id: int
) -> bool:
    """Record that we sent this trainer a notification about this request. False if another worker already inserted."""
    try:
        await session.execute(
            text("""
                INSERT INTO client_request_notifications (client_request_id, trainer_id)
                VALUES (:rid, :tid)
            """),
            {"rid": request_id, "tid": trainer_id},
        )
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def get_pending_response_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Responses where client_notified_at is null. Returns: response_id, request_id, client_telegram_id,
    city_name, service_name, responder_name, trainer_comment.
    """
    r = await session.execute(
        text("""
            SELECT resp.id, resp.client_request_id, cl.telegram_id,
                   c.name AS city_name, s.name AS service_name,
                   COALESCE(TRIM(CONCAT(tp.first_name, ' ', tp.last_name)), 'Тренер') AS responder_name,
                   resp.trainer_comment
            FROM client_request_responses resp
            INNER JOIN client_requests req ON req.id = resp.client_request_id
            INNER JOIN clients cl ON cl.id = req.client_id
            INNER JOIN cities c ON c.id = req.city_id
            INNER JOIN services s ON s.id = req.service_id
            INNER JOIN trainers t ON t.id = resp.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE resp.client_notified_at IS NULL
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [
        {
            "response_id": row[0],
            "request_id": row[1],
            "client_telegram_id": row[2],
            "city_name": row[3],
            "service_name": row[4],
            "responder_name": row[5],
            "trainer_comment": (row[6] or "").strip() or None,
        }
        for row in rows
    ]


async def mark_response_notified(session: AsyncSession, response_id: int) -> None:
    """Mark that we notified the client about this response."""
    await session.execute(
        text("""
            UPDATE client_request_responses SET client_notified_at = NOW() WHERE id = :id
        """),
        {"id": response_id},
    )
    await session.commit()


async def get_pending_no_response_reminders(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Requests created >= 2 days ago, with 0 responses, reminder not sent yet.
    Returns: request_id, client_telegram_id.
    """
    r = await session.execute(
        text("""
            SELECT req.id, cl.telegram_id
            FROM client_requests req
            INNER JOIN clients cl ON cl.id = req.client_id
            LEFT JOIN client_request_responses resp ON resp.client_request_id = req.id
            WHERE req.created_at <= NOW() - INTERVAL '2 days'
              AND req.no_response_reminder_sent_at IS NULL
              AND req.status = 'new'
            GROUP BY req.id, cl.telegram_id
            HAVING COUNT(resp.id) = 0
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = r.fetchall()
    return [{"request_id": row[0], "client_telegram_id": row[1]} for row in rows]


async def mark_no_response_reminder_sent(session: AsyncSession, request_id: int) -> None:
    """Mark that we sent the no-response reminder for this request."""
    await session.execute(
        text("""
            UPDATE client_requests SET no_response_reminder_sent_at = NOW() WHERE id = :id
        """),
        {"id": request_id},
    )
    await session.commit()
