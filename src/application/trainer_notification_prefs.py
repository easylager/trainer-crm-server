"""
Per-trainer window for Telegram pushes from notification_service (Europe/Minsk wall clock).
NULL in DB = use platform default from notification_hours (08:00–22:00).
"""
from __future__ import annotations

from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import (
    NOTIFICATION_END_HOUR,
    NOTIFICATION_START_HOUR,
    NOTIFICATION_TZ,
    is_quiet_hours_bypass_active,
)


def validate_push_notification_window(start_h: int, end_h: int) -> None:
    """Raise ValueError if window is invalid."""
    if start_h < 0 or start_h > 23:
        raise ValueError("Час начала окна: от 0 до 23.")
    if end_h < 1 or end_h > 24:
        raise ValueError("Час окончания окна: от 1 до 24 (конец не включается).")
    if start_h == end_h:
        raise ValueError("Окно не может быть пустым: задайте разные часы или сбросьте к стандарту.")
    # Same calendar day [start, end): need end > start, or overnight wrap (start > end)
    if start_h < end_h:
        return
    # Overnight e.g. 22–8
    if start_h > end_h:
        return
    raise ValueError("Некорректное окно уведомлений.")


def is_local_time_in_push_window(now_t: time, start_h: int, end_h: int) -> bool:
    """
    True if now_t falls in the push window. Same-day [start_h, end_h); overnight if start_h > end_h.
    Full day: start_h=0, end_h=24 → always True for normal clock times.
    """
    h = now_t.hour
    if start_h == end_h:
        return False
    if start_h < end_h:
        return start_h <= h < end_h
    return h >= start_h or h < end_h


async def get_trainer_push_window_bounds(
    session: AsyncSession, trainer_id: int
) -> tuple[int, int]:
    """Resolved start/end hours (Europe/Minsk); NULL columns → platform default."""
    r = await session.execute(
        text(
            "SELECT push_notification_start_hour, push_notification_end_hour "
            "FROM trainers WHERE id = :id"
        ),
        {"id": trainer_id},
    )
    row = r.fetchone()
    if not row:
        return NOTIFICATION_START_HOUR, NOTIFICATION_END_HOUR
    sh, eh = row[0], row[1]
    if sh is None or eh is None:
        return NOTIFICATION_START_HOUR, NOTIFICATION_END_HOUR
    return int(sh), int(eh)


async def is_trainer_push_allowed_now(
    session: AsyncSession, trainer_id: int
) -> bool:
    """
    Whether notification_service may send this trainer a Telegram push now.
    Global NOTIFICATION_DISABLE_QUIET_HOURS bypasses all windows.
    """
    if is_quiet_hours_bypass_active():
        return True
    start_h, end_h = await get_trainer_push_window_bounds(session, trainer_id)
    now = datetime.now(ZoneInfo(NOTIFICATION_TZ)).time()
    return is_local_time_in_push_window(now, start_h, end_h)
