"""Какие напоминания ставить. Дневное пропускаем, если до старта меньше суток."""

from __future__ import annotations

from datetime import datetime, timedelta

DAY = "day"
HOUR = "hour"
FOLLOWUP = "organizer_followup"
AFTER = "after"
WEEKLY = "weekly"

PENDING = "pending"
SKIPPED = "skipped"


def plan(
    *,
    created_at: datetime,
    starts_at: datetime,
    ends_at: datetime,
    weekly_in_chat: bool,
) -> list[tuple[str, datetime, str]]:
    day_due = starts_at - timedelta(days=1)
    day_status = PENDING if created_at <= day_due else SKIPPED
    rows = [
        (DAY, day_due, day_status),
        (HOUR, starts_at - timedelta(hours=1), PENDING),
        (FOLLOWUP, created_at + timedelta(hours=24), PENDING),
        (AFTER, ends_at, PENDING),
    ]
    if weekly_in_chat:
        rows.append((WEEKLY, ends_at + timedelta(days=7), PENDING))
    return rows
