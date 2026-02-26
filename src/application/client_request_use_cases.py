"""
Client request use cases: create request, list for trainer (matching city+service), respond, list for client with responses.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_client_request(
    session: AsyncSession,
    client_telegram_id: int,
    city_id: int,
    service_id: int,
    comment: str | None = None,
) -> int:
    """Insert client_requests row. Returns new id."""
    r = await session.execute(
        text("""
            INSERT INTO client_requests (client_telegram_id, city_id, service_id, comment, status)
            VALUES (:tid, :cid, :sid, :comment, 'new')
            RETURNING id
        """),
        {
            "tid": client_telegram_id,
            "cid": city_id,
            "sid": service_id,
            "comment": (comment or "").strip() or None,
        },
    )
    (pk,) = r.fetchone()
    await session.commit()
    return pk


async def list_requests_for_trainer(
    session: AsyncSession,
    trainer_id: int,
    limit: int = 50,
) -> list[dict]:
    """
    Requests visible to this trainer: status=new, same city as trainer profile, same service in trainer_services.
    Each row includes has_responded (this trainer already responded).
    """
    r = await session.execute(
        text("""
            SELECT r.id, r.city_id, r.service_id, r.comment, r.created_at,
                   c.name AS city_name,
                   s.name AS service_name,
                   (SELECT 1 FROM client_request_responses resp
                    WHERE resp.client_request_id = r.id AND resp.trainer_id = :tid) IS NOT NULL AS has_responded
            FROM client_requests r
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainer_profiles p ON p.trainer_id = :tid AND p.city_id = r.city_id
            INNER JOIN trainer_services ts ON ts.trainer_id = :tid AND ts.service_id = r.service_id
            WHERE r.status = 'new'
            ORDER BY r.created_at DESC
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
            "has_responded": bool(row[7]),
        }
        for row in rows
    ]


async def create_request_response(
    session: AsyncSession,
    client_request_id: int,
    trainer_id: int,
) -> int | None:
    """
    Trainer responds to request. Returns response id if created; None if request not found,
    trainer doesn't match request (city+service), or already responded.
    """
    # Check request exists and trainer matches (city + service)
    check = await session.execute(
        text("""
            SELECT r.id FROM client_requests r
            INNER JOIN trainer_profiles p ON p.trainer_id = :tid AND p.city_id = r.city_id
            INNER JOIN trainer_services ts ON ts.trainer_id = :tid AND ts.service_id = r.service_id
            WHERE r.id = :rid AND r.status = 'new'
        """),
        {"tid": trainer_id, "rid": client_request_id},
    )
    if not check.fetchone():
        return None
    # Already responded?
    exists = await session.execute(
        text("""
            SELECT id FROM client_request_responses
            WHERE client_request_id = :rid AND trainer_id = :tid
        """),
        {"rid": client_request_id, "tid": trainer_id},
    )
    if exists.fetchone():
        return None
    r = await session.execute(
        text("""
            INSERT INTO client_request_responses (client_request_id, trainer_id)
            VALUES (:rid, :tid)
            RETURNING id
        """),
        {"rid": client_request_id, "tid": trainer_id},
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
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            WHERE r.client_telegram_id = :tid AND r.status != 'archived'
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
                SELECT resp.trainer_id, tp.first_name, tp.last_name, t.telegram_id
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


# --- Notifications: trainer about new request, client about new response ---


async def get_pending_request_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Pairs (request, trainer) where request is new, trainer matches city+service, not yet notified.
    Returns list of dicts: request_id, trainer_id, trainer_telegram_id, city_name, service_name, comment.
    """
    r = await session.execute(
        text("""
            SELECT r.id, t.id AS trainer_id, t.telegram_id,
                   c.name AS city_name, s.name AS service_name, r.comment
            FROM client_requests r
            INNER JOIN cities c ON c.id = r.city_id
            INNER JOIN services s ON s.id = r.service_id
            INNER JOIN trainer_profiles p ON p.city_id = r.city_id
            INNER JOIN trainer_services ts ON ts.trainer_id = p.trainer_id AND ts.service_id = r.service_id
            INNER JOIN trainers t ON t.id = p.trainer_id AND t.telegram_id IS NOT NULL
            LEFT JOIN client_request_notifications n ON n.client_request_id = r.id AND n.trainer_id = t.id
            WHERE r.status = 'new' AND n.id IS NULL
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


async def get_pending_response_notifications(session: AsyncSession, limit: int = 50) -> list[dict]:
    """
    Responses where client_notified_at is null. Returns list of dicts: response_id, client_telegram_id,
    city_name, service_name, responder_name.
    """
    r = await session.execute(
        text("""
            SELECT resp.id, req.client_telegram_id,
                   c.name AS city_name, s.name AS service_name,
                   COALESCE(TRIM(CONCAT(tp.first_name, ' ', tp.last_name)), 'Тренер') AS responder_name
            FROM client_request_responses resp
            INNER JOIN client_requests req ON req.id = resp.client_request_id
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
            "client_telegram_id": row[1],
            "city_name": row[2],
            "service_name": row[3],
            "responder_name": row[4],
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
