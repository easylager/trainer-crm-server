"""Tickets for booked ice time (TASK-331).

Two pushes on top of the regular reminders:

* client: «билеты на ваш сеанс заканчиваются» once the rink's fresh Korona snapshot
  shows half the seats gone — popular hours sell out in the last hour;
* trainer: clients without the bot get nothing from us, so the trainer receives
  a list plus a share button per client with a ready message and the ticket link.

Both are journaled in ``reminders`` (status ``sent``/``failed``) under their own kinds,
so the regular reminder loop never picks them up.
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_arena_tickets import TICKET_SNAPSHOT_MAX_AGE
from src.application.booking_use_cases import SQL_BOOKING_RESOLVED_ARENA_ID_FOR_CLIENT
from src.application.family_access_use_cases import list_family_access_telegram_ids_for_reminders
from src.bot.messages import client_booking_tickets_button_label
from src.shared.html_template import safe_external_url
from src.shared.notification_hours import NOTIFICATION_TZ

logger = logging.getLogger(__name__)

KIND_TICKETS_LOW = "tickets_low"
# client_telegram_id holds the trainer's chat id for this kind.
KIND_TRAINER_TICKETS_FORWARD = "trainer_tickets_forward"
TICKET_PUSH_KINDS = (KIND_TICKETS_LOW, KIND_TRAINER_TICKETS_FORWARD)

LOW_TICKETS_SHARE = 0.5
LOW_TICKETS_MIN_LEAD = timedelta(minutes=15)
TRAINER_FORWARD_EVENING_FROM = time(19, 0)
TRAINER_FORWARD_MIN_LEAD = timedelta(minutes=60)
SEND_DELAY_SEC = 0.05

_ACTIVE_BOOKING_SQL = "b.status NOT IN ('cancelled', 'declined', 'trainer_removed', 'completed') AND NOT b.is_sandbox"

_BOOKINGS_SQL = f"""
SELECT b.id, b.client_id, b.trainer_id, s.slot_date, s.start_time,
       a.name AS arena_name, ap.tickets_url, x.arena_id,
       TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
       t.telegram_id AS trainer_telegram_id
FROM bookings b
JOIN slots s ON s.id = b.slot_id
JOIN clients c ON c.id = b.client_id
JOIN trainers t ON t.id = b.trainer_id
LEFT JOIN trainer_services ts ON ts.trainer_id = b.trainer_id AND ts.service_id = b.service_id
CROSS JOIN LATERAL (SELECT ({SQL_BOOKING_RESOLVED_ARENA_ID_FOR_CLIENT}) AS arena_id) x
JOIN arenas a ON a.id = x.arena_id
JOIN arena_profiles ap ON ap.arena_id = x.arena_id
WHERE {_ACTIVE_BOOKING_SQL}
  AND s.slot_date BETWEEN :d_from AND :d_to
  AND COALESCE(btrim(ap.tickets_url), '') <> ''
  AND NOT EXISTS (SELECT 1 FROM reminders r WHERE r.booking_id = b.id AND r.kind = :kind)
ORDER BY s.slot_date, s.start_time, b.id
"""

_LATEST_SNAPSHOT_SQL = """
SELECT DISTINCT ON (arena_id, starts_at_local)
       arena_id, starts_at_local, capacity, GREATEST(capacity - sold - held, 0) AS free
FROM ice_sales_snapshots
WHERE local_date = :d AND observed_at >= :fresh_since
ORDER BY arena_id, starts_at_local, observed_at DESC
"""


@dataclass(frozen=True)
class BookedTicket:
    booking_id: int
    client_id: int
    trainer_id: int
    slot_date: date
    start_time: time
    arena_id: int
    arena_name: str
    tickets_url: str
    client_name: str
    trainer_telegram_id: int | None


def _local(now: datetime) -> datetime:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(NOTIFICATION_TZ)
    return now.astimezone(tz) if now.tzinfo is not None else now.replace(tzinfo=tz)


def _starts_at(b: BookedTicket, now_local: datetime) -> datetime:
    return datetime.combine(b.slot_date, b.start_time, tzinfo=now_local.tzinfo)


async def _list_booked(session: AsyncSession, *, d_from: date, d_to: date, kind: str) -> list[BookedTicket]:
    rows = (
        await session.execute(text(_BOOKINGS_SQL), {"d_from": d_from, "d_to": d_to, "kind": kind})
    ).mappings().all()
    out: list[BookedTicket] = []
    for row in rows:
        url = safe_external_url(row["tickets_url"])
        if not url:
            continue
        out.append(
            BookedTicket(
                booking_id=int(row["id"]),
                client_id=int(row["client_id"]),
                trainer_id=int(row["trainer_id"]),
                slot_date=row["slot_date"],
                start_time=row["start_time"],
                arena_id=int(row["arena_id"]),
                arena_name=(row["arena_name"] or "").strip(),
                tickets_url=url,
                client_name=(row["client_name"] or "").strip() or "Клиент",
                trainer_telegram_id=int(row["trainer_telegram_id"]) if row["trainer_telegram_id"] else None,
            )
        )
    return out


def match_session_free(
    snapshots: dict[int, list[tuple[time, int, int]]], arena_id: int, start: time
) -> tuple[int, int] | None:
    """(free, capacity) of the public session that covers ``start`` (started ≤ 59 min earlier)."""
    best: tuple[time, int, int] | None = None
    start_min = start.hour * 60 + start.minute
    for starts_at, capacity, free in snapshots.get(arena_id, []):
        delta = start_min - (starts_at.hour * 60 + starts_at.minute)
        if 0 <= delta < 60 and (best is None or starts_at > best[0]):
            best = (starts_at, capacity, free)
    if best is None or not best[1]:
        return None
    return best[2], best[1]


def is_low(free: int, capacity: int) -> bool:
    return 0 < free <= capacity * LOW_TICKETS_SHARE


def format_low_tickets_text(*, arena_name: str, start: time, free: int, capacity: int) -> str:
    arena = html.escape(arena_name or "каток")
    return (
        "🎟 <b>Билеты на ваш сеанс заканчиваются</b>\n\n"
        f"Сегодня · {start.strftime('%H:%M')} · {arena}\n"
        f"Свободно {int(free)} из {int(capacity)}.\n\n"
        "Если билета ещё нет — возьмите сейчас онлайн 👇"
    )


def tickets_markup(*, url: str, arena_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=client_booking_tickets_button_label(arena_name), url=url)]]
    )


async def _journal(
    session: AsyncSession, *, booking_id: int, telegram_id: int, kind: str
) -> int:
    rid = (
        await session.execute(
            text(
                """
                INSERT INTO reminders (booking_id, client_telegram_id, kind, send_at, status, sent_at)
                VALUES (:bid, :tid, :kind, now(), 'sent', now())
                RETURNING id
                """
            ),
            {"bid": booking_id, "tid": telegram_id, "kind": kind},
        )
    ).scalar_one()
    await session.commit()
    return int(rid)


async def _mark_failed(session: AsyncSession, reminder_id: int, error: str) -> None:
    await session.execute(
        text("UPDATE reminders SET status = 'failed', sent_at = NULL, error = :err WHERE id = :id"),
        {"id": reminder_id, "err": error[:500]},
    )
    await session.commit()


async def send_low_ticket_alerts(session: AsyncSession, client_bot: Any, *, now: datetime) -> int:
    """One push per booking today whose session is at least half sold out. Returns pushes sent."""
    now_local = _local(now)
    today = now_local.date()
    booked = await _list_booked(session, d_from=today, d_to=today, kind=KIND_TICKETS_LOW)
    booked = [b for b in booked if _starts_at(b, now_local) - now_local >= LOW_TICKETS_MIN_LEAD]
    if not booked:
        return 0
    fresh_since = now.astimezone(timezone.utc) - TICKET_SNAPSHOT_MAX_AGE
    snapshots: dict[int, list[tuple[time, int, int]]] = defaultdict(list)
    for row in (await session.execute(text(_LATEST_SNAPSHOT_SQL), {"d": today, "fresh_since": fresh_since})).all():
        snapshots[int(row[0])].append((row[1], int(row[2]), int(row[3])))

    sent = 0
    for b in booked:
        seats = match_session_free(snapshots, b.arena_id, b.start_time)
        if seats is None or not is_low(*seats):
            continue
        free, capacity = seats
        tids = await list_family_access_telegram_ids_for_reminders(session, b.client_id)
        text_html = format_low_tickets_text(arena_name=b.arena_name, start=b.start_time, free=free, capacity=capacity)
        markup = tickets_markup(url=b.tickets_url, arena_name=b.arena_name)
        for tid in tids:
            rid = await _journal(session, booking_id=b.booking_id, telegram_id=tid, kind=KIND_TICKETS_LOW)
            try:
                await client_bot.send_message(chat_id=tid, text=text_html, reply_markup=markup)
                sent += 1
            except Exception as e:  # noqa: BLE001 — one blocked chat must not stop the rest
                logger.warning("tickets_low send booking=%s tid=%s: %s", b.booking_id, tid, e)
                await _mark_failed(session, rid, str(e))
            await asyncio.sleep(SEND_DELAY_SEC)
    return sent


def _day_word(slot_date: date, today: date) -> str:
    return "сегодня" if slot_date == today else "завтра"


TRAINER_FORWARD_MAX_BUTTONS = 8


def format_trainer_forward_text(rows: list[BookedTicket], *, today: date) -> str:
    lines = [
        f"{html.escape(b.client_name)} — {_day_word(b.slot_date, today)} {b.start_time.strftime('%H:%M')}, "
        f"{html.escape(b.arena_name)}"
        for b in rows
    ]
    who = "У ученика нет нашего бота" if len(rows) == 1 else "У этих учеников нет нашего бота"
    return (
        "🎟 <b>Напомните про билет</b>\n\n"
        + "\n".join(lines)
        + f"\n\n{who}. Кнопка откроет Telegram с готовым сообщением и ссылкой на кассу."
    )


def format_client_share_text(b: BookedTicket, *, today: date) -> str:
    """Trainer's voice; Telegram puts the ticket link above it."""
    first = b.client_name.split()[0] if b.client_name and b.client_name != "Клиент" else ""
    hello = f"{first}, напоминаю" if first else "Напоминаю"
    return (
        f"{hello}: {_day_word(b.slot_date, today)} в {b.start_time.strftime('%H:%M')} занятие "
        f"на катке «{b.arena_name or 'каток'}». Билет лучше купить заранее онлайн по ссылке — "
        "на популярные часы его раскупают за час до начала."
    )


def share_url(b: BookedTicket, *, today: date) -> str:
    return "https://t.me/share/url?" + urlencode(
        {"url": b.tickets_url, "text": format_client_share_text(b, today=today)}, quote_via=quote
    )


def trainer_forward_markup(rows: list[BookedTicket], *, today: date) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for b in rows[:TRAINER_FORWARD_MAX_BUTTONS]:
        label = (
            "📤 Отправить напоминание"
            if len(rows) == 1
            else f"📤 {b.client_name.split()[0]} · {b.start_time.strftime('%H:%M')}"
        )
        buttons.append([InlineKeyboardButton(text=label, url=share_url(b, today=today))])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trainer_forward_due(b: BookedTicket, now_local: datetime) -> bool:
    """Tomorrow's sessions from 19:00 the evening before; today's while there is still an hour left."""
    today = now_local.date()
    if b.slot_date == today:
        return _starts_at(b, now_local) - now_local >= TRAINER_FORWARD_MIN_LEAD
    if b.slot_date == today + timedelta(days=1):
        return now_local.time() >= TRAINER_FORWARD_EVENING_FROM
    return False


async def send_trainer_ticket_forwards(
    session: AsyncSession,
    trainer_bot: Any,
    *,
    now: datetime,
) -> int:
    """Per trainer: one message with a share button per client the client bot can't reach."""
    now_local = _local(now)
    today = now_local.date()
    booked = await _list_booked(
        session, d_from=today, d_to=today + timedelta(days=1), kind=KIND_TRAINER_TICKETS_FORWARD
    )
    by_trainer: dict[int, list[BookedTicket]] = defaultdict(list)
    for b in booked:
        if b.trainer_telegram_id is None or not trainer_forward_due(b, now_local):
            continue
        if await list_family_access_telegram_ids_for_reminders(session, b.client_id):
            continue
        by_trainer[b.trainer_telegram_id].append(b)

    sent = 0
    for trainer_tid, rows in by_trainer.items():
        rids = [
            await _journal(session, booking_id=b.booking_id, telegram_id=trainer_tid, kind=KIND_TRAINER_TICKETS_FORWARD)
            for b in rows
        ]
        try:
            await trainer_bot.send_message(
                chat_id=trainer_tid,
                text=format_trainer_forward_text(rows, today=today),
                reply_markup=trainer_forward_markup(rows, today=today),
            )
            sent += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("trainer_tickets_forward send trainer_tid=%s: %s", trainer_tid, e)
            for rid in rids:
                await _mark_failed(session, rid, str(e))
        await asyncio.sleep(SEND_DELAY_SEC)
    return sent
