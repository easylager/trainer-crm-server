"""«Первые три ученика» (TASK-310): шаг хаба сразу после расписания.

Воронка 2026-10-20: 12 из 33 тренеров собрали неделю, скопировали ссылку и ушли с пустым
календарём — ни одного клиента, ни одной записи. Ссылка ждёт, что ученик придёт сам; этот шаг
просит тренера перенести своих учеников: имя (телефон по желанию) и ближайшее окно его же недели.
Клиенту для этого ничего не нужно — бот он подключит позже по личной ссылке (``client_bind``).

Здесь — только чтение и создание клиента без телефона. Запись и «каждую неделю» идут через
те же маршруты, что у расписания, чтобы напоминания и уведомления не разъехались.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_profile_use_cases import sql_client_notify_telegram_id
from src.shared.notification_hours import NOTIFICATION_TZ

FIRST_STUDENTS_GOAL = 3
OPTIONS_HORIZON_DAYS = 14
OPTIONS_LIMIT = 8

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

# Клиенты тренера — тот же охват, что у CRM и подсказок хаба: записи, группы, ростер; без демо.
SQL_TRAINER_CRM_CLIENT_IDS = """
    SELECT b.client_id
    FROM bookings b
    JOIN clients c ON c.id = b.client_id
    WHERE b.trainer_id = :tid
      AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
      AND NOT b.is_sandbox
      AND NOT c.is_sandbox
    UNION
    SELECT m.client_id
    FROM training_group_members m
    JOIN training_groups g ON g.id = m.training_group_id
    JOIN clients c ON c.id = m.client_id
    WHERE g.trainer_id = :tid
      AND m.status IN ('active', 'trial')
      AND NOT c.is_sandbox
    UNION
    SELECT r.client_id
    FROM trainer_client_roster r
    JOIN clients c ON c.id = r.client_id
    WHERE r.trainer_id = :tid
      AND NOT c.is_sandbox
"""


def slot_label(slot_date: date, start_time: time, *, today: date) -> str:
    """«сегодня 18:00», «завтра 9:30», «пн 18:00» — ближние две недели, без числа месяца."""
    hhmm = f"{start_time.hour}:{start_time.minute:02d}"
    if slot_date == today:
        return f"сегодня {hhmm}"
    if slot_date == today + timedelta(days=1):
        return f"завтра {hhmm}"
    day = _WEEKDAYS[slot_date.weekday()]
    if slot_date - today >= timedelta(days=7):
        return f"{day} {slot_date.day:02d}.{slot_date.month:02d} {hhmm}"
    return f"{day} {hhmm}"


def initials(first_name: str | None, last_name: str | None) -> str:
    parts = [p.strip() for p in (first_name or "", last_name or "") if p and p.strip()]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _local_now() -> datetime:
    return datetime.now(ZoneInfo(NOTIFICATION_TZ))


def local_today() -> date:
    return _local_now().date()


async def count_trainer_crm_clients(session: AsyncSession, trainer_id: int) -> int:
    r = await session.execute(
        text(f"SELECT COUNT(*)::int FROM ({SQL_TRAINER_CRM_CLIENT_IDS}) q"),
        {"tid": int(trainer_id)},
    )
    return int(r.scalar() or 0)


async def list_slot_options(
    session: AsyncSession, trainer_id: int, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Ближайшие свободные окна тренера: то, что лист предлагает чипами «ближайшая тренировка»."""
    moment = now or _local_now()
    today = moment.date()
    r = await session.execute(
        text(
            """
            SELECT s.id, s.slot_date, s.start_time
            FROM slots s
            WHERE s.trainer_id = :tid
              AND s.status = 'available'
              AND s.training_group_id IS NULL
              AND (s.slot_date > :today OR (s.slot_date = :today AND s.start_time > :now_time))
              AND s.slot_date <= :until
            ORDER BY s.slot_date, s.start_time, s.id
            LIMIT :lim
            """
        ),
        {
            "tid": int(trainer_id),
            "today": today,
            "now_time": moment.time().replace(tzinfo=None),
            "until": today + timedelta(days=OPTIONS_HORIZON_DAYS),
            "lim": OPTIONS_LIMIT,
        },
    )
    return [
        {"slot_id": int(row[0]), "label": slot_label(row[1], row[2], today=today)}
        for row in r.fetchall()
    ]


async def list_first_students(
    session: AsyncSession, trainer_id: int, *, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Первые клиенты тренера (по порядку появления) — аватарки на местах карточки."""
    moment = now or _local_now()
    today = moment.date()
    r = await session.execute(
        text(
            f"""
            WITH rel AS ({SQL_TRAINER_CRM_CLIENT_IDS}),
            nxt AS (
                SELECT DISTINCT ON (b.client_id) b.client_id, s.slot_date, s.start_time
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('pending', 'confirmed')
                  AND NOT b.is_sandbox
                  AND (s.slot_date > :today OR (s.slot_date = :today AND s.start_time > :now_time))
                ORDER BY b.client_id, s.slot_date, s.start_time
            )
            SELECT c.id, c.first_name, c.last_name,
                   ({sql_client_notify_telegram_id("c")}) IS NOT NULL AS has_bot,
                   nxt.slot_date, nxt.start_time
            FROM rel
            JOIN clients c ON c.id = rel.client_id
            LEFT JOIN nxt ON nxt.client_id = c.id
            ORDER BY c.id
            LIMIT :lim
            """
        ),
        {
            "tid": int(trainer_id),
            "today": today,
            "now_time": moment.time().replace(tzinfo=None),
            "lim": FIRST_STUDENTS_GOAL,
        },
    )
    out: list[dict[str, Any]] = []
    for row in r.fetchall():
        first, last = (row[1] or "").strip(), (row[2] or "").strip()
        out.append(
            {
                "client_id": int(row[0]),
                "name": first or last or "Ученик",
                "initials": initials(first, last),
                "has_bot": bool(row[3]),
                "next_label": slot_label(row[4], row[5], today=today) if row[4] else None,
            }
        )
    return out


async def first_students_state(
    session: AsyncSession, trainer_id: int, *, now: datetime | None = None
) -> dict[str, Any]:
    return {
        "goal": FIRST_STUDENTS_GOAL,
        "count": await count_trainer_crm_clients(session, trainer_id),
        "students": await list_first_students(session, trainer_id, now=now),
        "options": await list_slot_options(session, trainer_id, now=now),
    }


async def create_client_without_phone(
    session: AsyncSession, *, first_name: str, last_name: str | None = None
) -> int:
    """Клиент только по имени: телефон тренер может не знать или не хотеть вводить.

    Такой клиент ни с кем не склеится по номеру — к Telegram его привяжет личная ссылка
    ``client_bind``, она номера не требует. Caller commits.
    """
    r = await session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name)
            VALUES (:first_name, :last_name)
            RETURNING id
            """
        ),
        {"first_name": first_name.strip()[:64], "last_name": (last_name or "").strip()[:64] or None},
    )
    return int(r.scalar_one())
