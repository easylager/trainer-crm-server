"""
Неделя для главной тренера (TASK-314, волна 2): полоса дней, «Неделя: N занятий, M окон» и
свободные окна в пустой день — одним запросом внутри ``hub/bootstrap``.

Занятие — живая запись (не отменённая и не отклонённая). Свободное окно — слот в статусе
``available``, который ещё не начался. Время — как его видит тренер, в ``NOTIFICATION_TZ``.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import NOTIFICATION_TZ

LIVE_BOOKING_STATUSES = ("pending", "confirmed", "completed")
MAX_FREE_TIMES_PER_DAY = 6


async def hub_week_summary(
    session: AsyncSession, trainer_id: int, today: date, days: int = 7
) -> dict[str, Any]:
    """``{"days": [{date, sessions, pending, free, free_times}], "sessions", "free"}`` на ``days`` дней."""
    end = today + timedelta(days=days - 1)
    r_book = await session.execute(
        text(
            """
            SELECT s.slot_date,
                   COUNT(*) AS sessions,
                   COUNT(*) FILTER (WHERE b.status = 'pending') AS pending
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid
              AND s.slot_date BETWEEN :d0 AND :d1
              AND b.status = ANY(:statuses)
            GROUP BY s.slot_date
            """
        ),
        {"tid": int(trainer_id), "d0": today, "d1": end, "statuses": list(LIVE_BOOKING_STATUSES)},
    )
    booked = {row[0]: (int(row[1]), int(row[2])) for row in r_book.fetchall()}

    r_free = await session.execute(
        text(
            """
            SELECT slot_date, start_time
            FROM slots
            WHERE trainer_id = :tid
              AND status = 'available'
              AND slot_date BETWEEN :d0 AND :d1
              AND ((slot_date + start_time) AT TIME ZONE :tz) > NOW()
            ORDER BY slot_date, start_time
            """
        ),
        {"tid": int(trainer_id), "d0": today, "d1": end, "tz": NOTIFICATION_TZ},
    )
    free: dict[date, list[str]] = {}
    for d, t in r_free.fetchall():
        free.setdefault(d, []).append(f"{t.hour}:{t.minute:02d}")

    out_days = []
    total_sessions = 0
    total_free = 0
    for i in range(days):
        d = today + timedelta(days=i)
        sessions, pending = booked.get(d, (0, 0))
        times = free.get(d, [])
        total_sessions += sessions
        total_free += len(times)
        out_days.append(
            {
                "date": d.isoformat(),
                "sessions": sessions,
                "pending": pending,
                "free": len(times),
                "free_times": times[:MAX_FREE_TIMES_PER_DAY],
            }
        )
    return {"days": out_days, "sessions": total_sessions, "free": total_free}
