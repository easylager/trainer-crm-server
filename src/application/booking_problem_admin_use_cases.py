"""
PRD E6: admin listing of booking problem reports (audit visibility, blacklist pipeline).
Read-only; source of truth remains immutable `booking_problem_reports` + JSON audit lines.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def count_booking_problem_reports_for_admin(
    session: AsyncSession,
    *,
    blacklist_only: bool = False,
) -> int:
    """Total rows matching filter (for admin UI captions)."""
    r = await session.execute(
        text(
            """
            SELECT COUNT(*) FROM booking_problem_reports
            WHERE CASE WHEN :bl_only THEN blacklist_candidate = true ELSE true END
            """
        ),
        {"bl_only": blacklist_only},
    )
    n = r.scalar()
    return int(n or 0)


async def list_booking_problem_reports_for_admin(
    session: AsyncSession,
    *,
    limit: int = 15,
    offset: int = 0,
    blacklist_only: bool = False,
) -> list[dict[str, Any]]:
    """
    Recent reports with booking/slot identifiers (no client PII).
    Ordered by created_at DESC.
    """
    lim = max(1, min(int(limit), 100))
    off = max(0, int(offset))
    r = await session.execute(
        text(
            """
            SELECT pr.id, pr.booking_id, pr.trainer_id, pr.client_id, pr.preset_id, pr.payment_class,
                   pr.source, pr.blacklist_candidate, pr.policy_breach_code, pr.created_at,
                   s.slot_date, s.start_time, s.end_time,
                   b.status AS booking_status
            FROM booking_problem_reports pr
            JOIN bookings b ON b.id = pr.booking_id
            JOIN slots s ON s.id = b.slot_id
            WHERE CASE WHEN :bl_only THEN pr.blacklist_candidate = true ELSE true END
            ORDER BY pr.created_at DESC
            LIMIT :lim OFFSET :off
            """
        ),
        {"bl_only": blacklist_only, "lim": lim, "off": off},
    )
    rows = r.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": int(row[0]),
                "booking_id": int(row[1]),
                "trainer_id": int(row[2]),
                "client_id": int(row[3]),
                "preset_id": (row[4] or "").strip(),
                "payment_class": (row[5] or "").strip(),
                "source": (row[6] or "").strip(),
                "blacklist_candidate": bool(row[7]),
                "policy_breach_code": (row[8] or "").strip() or None,
                "created_at": row[9],
                "slot_date": row[10],
                "start_time": row[11],
                "end_time": row[12],
                "booking_status": (row[13] or "").strip(),
            }
        )
    return out
