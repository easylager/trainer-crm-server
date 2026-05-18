"""Completed-session milestone pushes (5 / 10 / 25): DB idempotency + effort inputs."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SESSION_MILESTONE_TARGETS = (5, 10, 25)

# Fewer completed clients → percentile is noisy; omit line below this cohort size.
MIN_CLIENTS_FOR_ENGAGEMENT_PERCENTILE = 30


async def try_claim_session_milestone_notification(
    session: AsyncSession,
    *,
    client_id: int,
    milestone_target: int,
    completed_total: int,
) -> bool:
    """
    Insert dedupe row if eligible. Returns True when this worker owns the send.

    Caller must send Telegram and call ``release_session_milestone_claim`` if send fails.
    """
    if milestone_target not in SESSION_MILESTONE_TARGETS:
        return False
    if completed_total < milestone_target:
        return False
    r = await session.execute(
        text(
            """
            INSERT INTO client_session_milestone_notifications (
                client_id, milestone_target, completed_total_at_send
            )
            VALUES (:cid, :m, :total)
            ON CONFLICT (client_id, milestone_target) DO NOTHING
            RETURNING id
            """
        ),
        {"cid": client_id, "m": milestone_target, "total": completed_total},
    )
    row = r.fetchone()
    await session.commit()
    return row is not None


async def release_session_milestone_claim(
    session: AsyncSession,
    *,
    client_id: int,
    milestone_target: int,
) -> None:
    """Undo claim when Telegram send failed so a retry can celebrate later."""
    await session.execute(
        text(
            """
            DELETE FROM client_session_milestone_notifications
            WHERE client_id = :cid AND milestone_target = :m
            """
        ),
        {"cid": client_id, "m": milestone_target},
    )
    await session.commit()


async def fetch_completed_session_effort_rows(
    session: AsyncSession,
    client_id: int,
) -> list[tuple[float, str]]:
    """
    (duration_minutes, service_name) for all non-sandbox completed bookings.

    Duration from slot wall interval; caps absurd gaps defensively.
    """
    r = await session.execute(
        text(
            """
            SELECT
                LEAST(240.0, GREATEST(1.0,
                    (EXTRACT(EPOCH FROM (s.end_time - s.start_time)) / 60.0)
                )) AS minutes,
                srv.name AS service_name
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN services srv ON srv.id = b.service_id
            WHERE b.client_id = :cid
              AND b.status = 'completed'
              AND NOT b.is_sandbox
            ORDER BY s.slot_date ASC, s.start_time ASC
            """
        ),
        {"cid": client_id},
    )
    out: list[tuple[float, str]] = []
    for minutes, name in r.fetchall():
        svc = (name or "").strip() or "Услуга"
        out.append((float(minutes or 1.0), svc))
    return out


async def fetch_engagement_percentile_vs_clients_below_threshold(
    session: AsyncSession,
    *,
    completed_sessions_threshold: int,
    min_clients: int = MIN_CLIENTS_FOR_ENGAGEMENT_PERCENTILE,
) -> int | None:
    """
    Among clients with ≥1 non-sandbox completed booking: floor share (0–99) that have
    strictly fewer completed bookings than ``completed_sessions_threshold``.

    Example: threshold 5 → clients with 1–4 completions vs everyone with ≥1.
    ``None`` when the cohort is too small.
    """
    thr = int(completed_sessions_threshold)
    if thr < 2:
        return None
    r = await session.execute(
        text(
            """
            WITH totals AS (
                SELECT b.client_id, COUNT(*)::bigint AS cnt
                FROM bookings b
                WHERE b.status = 'completed' AND NOT b.is_sandbox
                GROUP BY b.client_id
            ),
            agg AS (
                SELECT
                    COUNT(*) FILTER (WHERE cnt >= 1)::bigint AS with_any,
                    COUNT(*) FILTER (WHERE cnt >= 1 AND cnt < :thr)::bigint AS below_thr
                FROM totals
            )
            SELECT with_any, below_thr FROM agg
            """
        ),
        {"thr": thr},
    )
    row = r.fetchone()
    if not row:
        return None
    with_any, below_thr = int(row[0] or 0), int(row[1] or 0)
    if with_any < int(min_clients):
        return None
    if with_any <= 0:
        return None
    pct = int(100.0 * below_thr / float(with_any))
    return max(0, min(99, pct))
