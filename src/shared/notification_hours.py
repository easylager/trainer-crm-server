"""
Working hours for user notifications: send only between 08:00 and 22:00 (Europe/Minsk).
Outside this window, notifier loops skip sending; next run after 08:00 will deliver.
Also used for "min hours before booking": only time inside this window counts.

Bypass (24/7 pushes): set env ``NOTIFICATION_DISABLE_QUIET_HOURS=1`` (see Settings) and restart
``notification_service`` — ``notification_service`` calls ``set_notification_quiet_hours_bypass`` on startup.
"""
from datetime import date, datetime, time, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

NOTIFICATION_TZ = "Europe/Minsk"
NOTIFICATION_START_HOUR = 8   # 08:00 inclusive
NOTIFICATION_END_HOUR = 22    # 22:00 exclusive (up to 21:59:59)

# Set by notification_service from Settings (or tests); when True, all notifier loops may send anytime.
_bypass_quiet_hours: bool = False


def set_notification_quiet_hours_bypass(disable_quiet_hours: bool) -> None:
    """When True, ``is_within_notification_hours()`` always returns True (no night pause)."""
    global _bypass_quiet_hours
    _bypass_quiet_hours = bool(disable_quiet_hours)


def is_within_notification_hours() -> bool:
    """True if current time in NOTIFICATION_TZ is in [08:00, 22:00), or quiet hours are bypassed."""
    if _bypass_quiet_hours:
        return True
    now = datetime.now(ZoneInfo(NOTIFICATION_TZ)).time()
    return time(NOTIFICATION_START_HOUR, 0) <= now < time(NOTIFICATION_END_HOUR, 0)


def working_hours_between(
    now_utc_or_minsk: datetime,
    slot_date: date,
    slot_start_time: time,
    *,
    tz: str = NOTIFICATION_TZ,
    start_hour: int = NOTIFICATION_START_HOUR,
    end_hour: int = NOTIFICATION_END_HOUR,
) -> float:
    """
    Hours of "working time" (within [start_hour, end_hour) in tz) between now and slot start.
    If now_utc_or_minsk is naive, treat as Minsk; if aware, convert to tz. Slot is in tz.
    Used so clients only see slots that are at least N working hours away (trainer setting).
    """
    if now_utc_or_minsk.tzinfo is None:
        now = now_utc_or_minsk.replace(tzinfo=ZoneInfo(tz))
    else:
        now = now_utc_or_minsk.astimezone(ZoneInfo(tz))
    slot_naive = datetime.combine(slot_date, slot_start_time)
    slot_dt = slot_naive.replace(tzinfo=ZoneInfo(tz))
    if slot_dt <= now:
        return 0.0
    total = 0.0
    cur = now
    while cur.date() < slot_dt.date():
        work_start = max(cur, cur.replace(hour=start_hour, minute=0, second=0, microsecond=0))
        work_end = cur.replace(hour=end_hour, minute=0, second=0, microsecond=0)
        if work_start < work_end:
            total += (work_end - work_start).total_seconds() / 3600.0
        cur = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    work_start = max(cur, cur.replace(hour=start_hour, minute=0, second=0, microsecond=0))
    work_end = min(slot_dt, cur.replace(hour=end_hour, minute=0, second=0, microsecond=0))
    if work_start < work_end:
        total += (work_end - work_start).total_seconds() / 3600.0
    return total
