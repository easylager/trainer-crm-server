"""
Client request use cases: create request, list for trainer (matching city+service), respond, list for client with responses.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
                   r.client_id,
                   cl.telegram_id AS client_telegram_id,
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
            "client_id": row[9],
            "client_telegram_id": row[10],
            "client_first_name": (row[11] or "").strip() or None,
            "client_last_name": (row[12] or "").strip() or None,
        }
        for row in rows
    ]


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
    """Trainer said "remind me when I have slots". Idempotent: one row per (trainer, request)."""
    await session.execute(
        text("""
            INSERT INTO trainer_pending_request_booking (trainer_id, client_request_id)
            VALUES (:tid, :rid)
            ON CONFLICT (trainer_id, client_request_id) DO NOTHING
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    await session.commit()
    return True


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
    r = await session.execute(
        text("""
            SELECT DISTINCT p.trainer_id, t.telegram_id, p.client_request_id
            FROM trainer_pending_request_booking p
            INNER JOIN trainers t ON t.id = p.trainer_id AND t.telegram_id IS NOT NULL
            INNER JOIN client_requests r ON r.id = p.client_request_id AND r.status != 'archived'
            INNER JOIN slots s ON s.trainer_id = p.trainer_id
              AND s.slot_date >= CURRENT_DATE
              AND s.slot_date <= CURRENT_DATE + INTERVAL '14 days'
              AND s.status = 'available'
            WHERE (
                :cooldown_minutes = 0
                OR p.last_reminder_sent_at IS NULL
                OR p.last_reminder_sent_at < NOW() - (INTERVAL '1 minute' * :cooldown_minutes)
            )
            LIMIT 50
        """),
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


async def list_my_requests_with_responses(
    session: AsyncSession,
    client_telegram_id: int,
    limit: int = 30,
) -> list[dict]:
    """
    Client's requests with list of responding trainers (id, name, telegram_id for link).
    """
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
                       tp.rating_avg, tp.rating_count, tp.experience_years, tp.description, tp.session_duration_minutes,
                       (SELECT ph.file_key FROM trainer_photos ph WHERE ph.trainer_id = resp.trainer_id ORDER BY ph.sort_order NULLS LAST, ph.id LIMIT 1) AS photo_key
                FROM client_request_responses resp
                INNER JOIN trainers t ON t.id = resp.trainer_id
                LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
                WHERE resp.client_request_id = :rid
                ORDER BY resp.created_at ASC
            """),
            {"rid": req_id},
        )
        responders = []
        for tr in resp_r.fetchall():
            first_name = (tr[1] or "").strip()
            last_name = (tr[2] or "").strip()
            name = f"{first_name} {last_name}".strip() or "Тренер"
            responders.append({
                "trainer_id": tr[0],
                "name": name,
                "telegram_id": tr[3],
                "telegram_username": (tr[4] or "").strip() or None,
                "trainer_comment": (tr[5] or "").strip() or None,
                "rating_avg": float(tr[6]) if tr[6] is not None else None,
                "rating_count": (tr[7] or 0) if tr[7] is not None else 0,
                "experience_years": tr[8],
                "description": (tr[9] or "").strip() or None,
                "session_duration_minutes": tr[10],
                "photo_key": tr[11],
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
    Returns list of dicts: request_id, trainer_id, trainer_telegram_id, city_name, service_name, comment.
    """
    r = await session.execute(
        text("""
            (
            SELECT r.id, t.id AS trainer_id, t.telegram_id,
                   c.name AS city_name, s.name AS service_name, r.comment
            FROM client_requests r
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainers t ON t.id = r.trainer_id AND t.telegram_id IS NOT NULL
            LEFT JOIN client_request_notifications n ON n.client_request_id = r.id AND n.trainer_id = t.id
            WHERE r.status = 'new' AND r.trainer_id IS NOT NULL AND n.id IS NULL
            )
            UNION ALL
            (
            SELECT r.id, t.id AS trainer_id, t.telegram_id,
                   c.name AS city_name, s.name AS service_name, r.comment
            FROM client_requests r
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
        }
        for row in rows
    ]


async def mark_request_trainer_notified(
    session: AsyncSession, request_id: int, trainer_id: int
) -> None:
    """Record that we sent this trainer a notification about this request."""
    await session.execute(
        text("""
            INSERT INTO client_request_notifications (client_request_id, trainer_id)
            VALUES (:rid, :tid)
        """),
        {"rid": request_id, "tid": trainer_id},
    )
    await session.commit()


async def get_trainers_for_daily_request_reminder(session: AsyncSession) -> list[dict]:
    """
    Trainers who: (1) have at least one open request (city+service, not responded/declined),
    (2) have not responded to any request in the last 2 days (we nudge inactive ones),
    (3) have not received this reminder in the last 2 days.
    Returns: trainer_id, trainer_telegram_id, request_count.
    """
    r = await session.execute(
        text("""
            SELECT t.id, t.telegram_id, COUNT(req.id) AS request_count
            FROM trainers t
            INNER JOIN trainer_profiles p ON p.trainer_id = t.id
            INNER JOIN trainer_services ts ON ts.trainer_id = t.id
            LEFT JOIN trainer_daily_request_reminder_sent rem
                ON rem.trainer_id = t.id AND rem.sent_date >= CURRENT_DATE - 2
            INNER JOIN client_requests req
                ON req.city_id = p.city_id AND req.service_id = ts.service_id AND req.status = 'new'
                AND NOT EXISTS (
                    SELECT 1 FROM client_request_responses resp
                    WHERE resp.client_request_id = req.id AND resp.trainer_id = t.id
                )
                AND NOT EXISTS (
                    SELECT 1 FROM client_request_declines d
                    WHERE d.client_request_id = req.id AND d.trainer_id = t.id
                )
            WHERE t.telegram_id IS NOT NULL
              AND rem.id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM client_request_responses any_resp
                  WHERE any_resp.trainer_id = t.id
                    AND any_resp.created_at >= NOW() - INTERVAL '2 days'
              )
            GROUP BY t.id, t.telegram_id
            HAVING COUNT(req.id) > 0
        """),
    )
    rows = r.fetchall()
    return [
        {"trainer_id": row[0], "trainer_telegram_id": row[1], "request_count": row[2]}
        for row in rows
    ]


async def mark_trainer_daily_request_reminder_sent(
    session: AsyncSession, trainer_id: int
) -> None:
    """Record that we sent today's request digest to this trainer."""
    await session.execute(
        text("""
            INSERT INTO trainer_daily_request_reminder_sent (trainer_id, sent_date)
            VALUES (:tid, CURRENT_DATE)
        """),
        {"tid": trainer_id},
    )
    await session.commit()


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
