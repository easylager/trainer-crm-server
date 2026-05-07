"""
Trainer↔client messages relayed through bots when native Telegram DM is unavailable.

Client receives via **client** bot; trainer receives via **trainer** bot — two bots, one server orchestrates both.
"""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import trainer_has_access_to_client

RELAY_SESSION_OPEN = "open"
RELAY_SESSION_CLOSED = "closed"
RELAY_SENDER_TRAINER = "trainer"
RELAY_SENDER_CLIENT = "client"

RELAY_BODY_MAX_LEN = 3800

# Strict product rule: auto-close inactive relay threads after 24h (not env-configurable).
RELAY_SESSION_IDLE_MINUTES = 24 * 60


async def relay_client_row_for_checks(session: AsyncSession, *, client_id: int) -> dict | None:
    r = await session.execute(
        text(
            """
            SELECT id,
                   telegram_id,
                   telegram_username,
                   COALESCE(is_sandbox, false) AS is_sandbox
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
        "telegram_id": int(row[1]) if row[1] is not None else None,
        "telegram_username": (row[2] or "").strip() or None,
        "is_sandbox": bool(row[3]),
    }


async def get_open_session_id(session: AsyncSession, *, trainer_id: int, client_id: int) -> int | None:
    r = await session.execute(
        text(
            """
            SELECT id FROM trainer_client_relay_sessions
            WHERE trainer_id = :tid AND client_id = :cid AND status = :st
            """
        ),
        {"tid": trainer_id, "cid": client_id, "st": RELAY_SESSION_OPEN},
    )
    row = r.fetchone()
    return int(row[0]) if row else None


async def open_relay_session(
    session: AsyncSession,
    *,
    trainer_id: int,
    client_id: int,
) -> int:
    sid = await get_open_session_id(session, trainer_id=trainer_id, client_id=client_id)
    if sid is not None:
        return sid
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_client_relay_sessions (trainer_id, client_id, status)
            VALUES (:tid, :cid, :st)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "cid": client_id, "st": RELAY_SESSION_OPEN},
    )
    row = r.fetchone()
    if not row:
        raise RuntimeError("relay_session_insert_failed")
    return int(row[0])


async def close_idle_open_relay_sessions(session: AsyncSession) -> list[dict]:
    """
    Mark open sessions with updated_at older than fixed 24h cutoff as closed.
    Returns rows for optional Telegram hints (trainer/client tg ids).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RELAY_SESSION_IDLE_MINUTES)
    # CTE keeps joins in a plain SELECT (no UPDATE-target alias limits in FROM/JOIN ON).
    r = await session.execute(
        text(
            """
            WITH doomed AS (
                SELECT rs_inner.id AS id,
                       t.telegram_id AS trainer_telegram_id,
                       c.telegram_id AS client_telegram_id
                FROM trainer_client_relay_sessions AS rs_inner
                INNER JOIN trainers AS t ON t.id = rs_inner.trainer_id
                INNER JOIN clients AS c ON c.id = rs_inner.client_id
                WHERE rs_inner.status = :open
                  AND rs_inner.updated_at < :cutoff
            )
            UPDATE trainer_client_relay_sessions AS rs
            SET status = :closed,
                closed_at = NOW(),
                updated_at = NOW()
            FROM doomed
            WHERE rs.id = doomed.id
            RETURNING rs.id,
                      doomed.trainer_telegram_id AS trainer_telegram_id,
                      doomed.client_telegram_id AS client_telegram_id
            """
        ),
        {
            "closed": RELAY_SESSION_CLOSED,
            "open": RELAY_SESSION_OPEN,
            "cutoff": cutoff,
        },
    )
    return [
        {
            "session_id": int(row[0]),
            "trainer_telegram_id": int(row[1]) if row[1] is not None else None,
            "client_telegram_id": int(row[2]) if row[2] is not None else None,
        }
        for row in r.fetchall()
    ]


async def insert_relay_message(
    session: AsyncSession,
    *,
    session_id: int,
    sender_role: str,
    body_text: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO trainer_client_relay_messages (session_id, sender_role, body_text)
            VALUES (:sid, :role, :body)
            """
        ),
        {"sid": session_id, "role": sender_role, "body": body_text},
    )
    await session.execute(
        text(
            """
            UPDATE trainer_client_relay_sessions
            SET updated_at = NOW() WHERE id = :sid AND status = :st
            """
        ),
        {"sid": session_id, "st": RELAY_SESSION_OPEN},
    )


async def close_relay_session(
    session: AsyncSession,
    *,
    session_id: int,
    trainer_id: int | None = None,
) -> bool:
    """
    Mark session closed. If trainer_id is set, ensures session belongs to that trainer (RBAC guard).
    """
    if trainer_id is not None:
        r = await session.execute(
            text(
                """
                UPDATE trainer_client_relay_sessions
                SET status = :closed, closed_at = NOW(), updated_at = NOW()
                WHERE id = :sid AND trainer_id = :tid AND status = :open
                """
            ),
            {"closed": RELAY_SESSION_CLOSED, "sid": session_id, "tid": trainer_id, "open": RELAY_SESSION_OPEN},
        )
    else:
        r = await session.execute(
            text(
                """
                UPDATE trainer_client_relay_sessions
                SET status = :closed, closed_at = NOW(), updated_at = NOW()
                WHERE id = :sid AND status = :open
                """
            ),
            {"closed": RELAY_SESSION_CLOSED, "sid": session_id, "open": RELAY_SESSION_OPEN},
        )
    return (r.rowcount or 0) > 0


async def relay_open_session_context_for_client_telegram(
    session: AsyncSession,
    *,
    client_telegram_id: int,
) -> dict | None:
    """
    Payload for inbound client-bot text: trainer id, telegram ids, session id.
    Client must belong to CRM row tied to relay session via client_id lookup.
    """
    r = await session.execute(
        text(
            """
            SELECT rs.id AS session_id,
                   rs.trainer_id,
                   rs.client_id,
                   t.telegram_id AS trainer_telegram_id,
                   c.telegram_id AS client_telegram_id
            FROM trainer_client_relay_sessions rs
            JOIN clients c ON c.id = rs.client_id
            JOIN trainers t ON t.id = rs.trainer_id
            WHERE rs.status = :open
              AND c.telegram_id = :ctid
            ORDER BY rs.updated_at DESC
            LIMIT 1
            """
        ),
        {"open": RELAY_SESSION_OPEN, "ctid": int(client_telegram_id)},
    )
    row = r.fetchone()
    if not row:
        return None
    return {
        "session_id": int(row[0]),
        "trainer_id": int(row[1]),
        "client_id": int(row[2]),
        "trainer_telegram_id": int(row[3]) if row[3] is not None else None,
        "client_telegram_id": int(row[4]) if row[4] is not None else None,
    }


async def relay_session_context_for_id(
    session: AsyncSession,
    *,
    session_id: int,
    trainer_id: int | None = None,
    client_id: int | None = None,
) -> dict | None:
    q = """
        SELECT rs.id,
               rs.trainer_id,
               rs.client_id,
               rs.status,
               t.telegram_id AS trainer_telegram_id,
               c.telegram_id AS client_telegram_id,
               c.first_name, c.last_name
        FROM trainer_client_relay_sessions rs
        JOIN clients c ON c.id = rs.client_id
        JOIN trainers t ON t.id = rs.trainer_id
        WHERE rs.id = :sid
    """
    params: dict = {"sid": session_id}
    if trainer_id is not None:
        q += " AND rs.trainer_id = :tid"
        params["tid"] = trainer_id
    if client_id is not None:
        q += " AND rs.client_id = :cid"
        params["cid"] = client_id
    r = await session.execute(text(q), params)
    row = r.fetchone()
    if not row:
        return None
    fn, ln = row[6], row[7]
    nm = ((fn or "").strip() + " " + (ln or "").strip()).strip()
    return {
        "session_id": int(row[0]),
        "trainer_id": int(row[1]),
        "client_id": int(row[2]),
        "status": str(row[3] or ""),
        "trainer_telegram_id": int(row[4]) if row[4] is not None else None,
        "client_telegram_id": int(row[5]) if row[5] is not None else None,
        "client_display_name": nm or "Клиент",
    }


def sanitize_relay_body(text_in: str) -> str | None:
    t = (text_in or "").strip()
    if not t:
        return None
    t = "\n".join(line.rstrip() for line in t.splitlines()).strip()
    if len(t) > RELAY_BODY_MAX_LEN:
        t = t[:RELAY_BODY_MAX_LEN] + "…"
    return t


async def assert_trainer_may_use_relay(
    session: AsyncSession,
    *,
    trainer_id: int,
    client_id: int,
) -> tuple[dict | None, str | None]:
    """
    Returns (client_row_or_none, error_code).
    error_code: 'not_found', 'sandbox', 'no_telegram', 'forbidden', None ok.
    """
    c_row = await relay_client_row_for_checks(session, client_id=client_id)
    if not c_row:
        return None, "not_found"
    if c_row["is_sandbox"]:
        return None, "sandbox"
    if not c_row.get("telegram_id"):
        return None, "no_telegram"
    if not await trainer_has_access_to_client(session, trainer_id, client_id):
        return None, "forbidden"
    return c_row, None


async def trainer_public_display_name(session: AsyncSession, *, trainer_id: int) -> str:
    r = await session.execute(
        text(
            """
            SELECT TRIM(
                CONCAT(
                    COALESCE(tp.first_name, ''),
                    ' ',
                    COALESCE(tp.last_name, '')
                )
            )
            FROM trainers t
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE t.id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    nm = (row[0] or "").strip() if row else ""
    return nm or "Тренер"
