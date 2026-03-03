"""
Working hours for user notifications: send only between 08:00 and 22:00 (Europe/Minsk).
Outside this window, notifier loops skip sending; next run after 08:00 will deliver.
"""
from datetime import datetime, time

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

NOTIFICATION_TZ = "Europe/Minsk"
NOTIFICATION_START_HOUR = 8   # 08:00 inclusive
NOTIFICATION_END_HOUR = 22    # 22:00 exclusive (up to 21:59:59)


def is_within_notification_hours() -> bool:
    """True if current time in NOTIFICATION_TZ is in [08:00, 22:00)."""
    now = datetime.now(ZoneInfo(NOTIFICATION_TZ)).time()
    return time(NOTIFICATION_START_HOUR, 0) <= now < time(NOTIFICATION_END_HOUR, 0)
