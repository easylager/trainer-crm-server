"""Диф сеансов после публикации и очередь сообщений «следить за катком» (TASK-213).

Сравниваем будущие ``public_skate|open_ice`` со основанием ``live|photo`` на 7 дней.
Ключ сеанса — ``local_date + starts_at_local + kind``. ``projected`` и дни за горизонтом
не считаются изменением. Первое наполнение пустой арены — не изменение.

Изменения одной арены в 30 минут склеиваются в одно сообщение, не чаще одного
сообщения об изменении за 6 часов на подписку. 22:00–08:00 Минск копим до 08:00.
Открытие (``season_closed`` → ``auto`` или первые сеансы после ≥14 дней без них)
гасит подписку, пока не нажали «Следить дальше».
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import groupby
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_follows import (
    BTN_KEEP,
    BTN_OPEN_SCHEDULE,
    BTN_SCHEDULE,
    BTN_UNFOLLOW,
    CB_KEEP_PREFIX,
    CB_UNFOLLOW_PREFIX,
    FollowButton,
    https_place_page_url,
)
from src.application.catalog_consumer_events import (
    KIND_FOLLOW_NOTIFIED,
    SURFACE_ARENA_FOLLOW,
    record_catalog_consumer_event,
    telegram_actor_hash,
)
from src.shared.notification_hours import NOTIFICATION_TZ, is_quiet_hours_bypass_active

logger = logging.getLogger(__name__)

FOLLOW_HORIZON_DAYS = 7
MERGE_WINDOW = timedelta(minutes=30)
MIN_GAP = timedelta(hours=6)
REOPEN_GAP = timedelta(days=14)
MAX_SEND_ATTEMPTS = 48
KIND_SCHEDULE = "schedule_changed"
KIND_REOPENED = "reopened"
OPENING_TAIL = "Больше об этом катке писать не будем, если не попросите."
_KINDS_SQL = "('public_skate', 'open_ice')"
_BASIS_SQL = "('live', 'photo')"
_WD_CAP = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")
_WD_LOW = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
_MINSK = ZoneInfo(NOTIFICATION_TZ)


class FollowBotBlocked(Exception):
    """Пользователь заблокировал бота или чата нет — подписку глушим."""


@dataclass(frozen=True)
class FollowSlot:
    local_date: date
    starts_at_local: time
    ends_at_local: time
    kind: str

    @property
    def key(self) -> tuple[date, time, str]:
        return (self.local_date, _minute(self.starts_at_local), self.kind)


@dataclass(frozen=True)
class FollowOutbound:
    notification_id: int
    follow_id: int
    telegram_id: int
    arena_id: int
    kind: str
    text: str
    buttons: tuple[FollowButton, ...]
    attempts: int


def _minute(value: time) -> time:
    return time(value.hour, value.minute)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _tz(name: str | None) -> ZoneInfo:
    raw = (name or "").strip() or NOTIFICATION_TZ
    try:
        return ZoneInfo(raw)
    except Exception:  # noqa: BLE001 — кривая таймзона арены не должна ронять публикацию
        return _MINSK


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
        return dict(loaded) if isinstance(loaded, dict) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _hhmm(moment: datetime, timezone_name: str | None) -> str:
    return _aware(moment).astimezone(_tz(timezone_name)).strftime("%H:%M")


def within_follow_hours(moment: datetime) -> bool:
    """08:00–22:00 Europe/Minsk, либо обход тихих часов notification_service."""
    if is_quiet_hours_bypass_active():
        return True
    local = _aware(moment).astimezone(_MINSK)
    return time(8, 0) <= local.time() < time(22, 0)


def push_out_of_quiet(moment: datetime) -> datetime:
    """Если момент в тихих часах — ближайшие 08:00 Минск. Иначе сам момент."""
    if is_quiet_hours_bypass_active():
        return _aware(moment)
    local = _aware(moment).astimezone(_MINSK)
    clock = local.time()
    if time(8, 0) <= clock < time(22, 0):
        return _aware(moment)
    if clock >= time(22, 0):
        nxt = (local + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    else:
        nxt = local.replace(hour=8, minute=0, second=0, microsecond=0)
    return nxt.astimezone(timezone.utc)


def schedule_not_before(
    *,
    now: datetime,
    batch_started_at: datetime,
    last_sent_at: datetime | None,
) -> datetime:
    """Не раньше конца 30-минутного окна, паузы 6 ч и выхода из тихих часов."""
    now_utc = _aware(now)
    gap = _aware(last_sent_at) + MIN_GAP if last_sent_at is not None else _aware(batch_started_at)
    if not within_follow_hours(now_utc):
        floor = push_out_of_quiet(now_utc)
        if last_sent_at is not None:
            floor = max(floor, gap)
        return floor
    debounce = _aware(batch_started_at) + MERGE_WINDOW
    return push_out_of_quiet(max(debounce, gap, now_utc))


def opening_not_before(*, now: datetime) -> datetime:
    """Открытие не ждёт 30 минут: только тихие часы."""
    now_utc = _aware(now)
    if within_follow_hours(now_utc):
        return now_utc
    return push_out_of_quiet(now_utc)


def _join_ru(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} и {parts[1]}"
    return ", ".join(parts[:-1]) + " и " + parts[-1]


def _by_day(slots: Iterable[FollowSlot]) -> list[tuple[date, list[FollowSlot]]]:
    ordered = sorted(slots, key=lambda slot: (slot.local_date, _minute(slot.starts_at_local), slot.kind))
    return [(day, list(group)) for day, group in groupby(ordered, key=lambda slot: slot.local_date)]


def _range_label(slot: FollowSlot) -> str:
    start = _minute(slot.starts_at_local).strftime("%H:%M")
    end = _minute(slot.ends_at_local).strftime("%H:%M")
    return f"{start}\u2013{end}"


def format_schedule_changed_html(
    place_name: str,
    removed: Sequence[FollowSlot],
    added: Sequence[FollowSlot],
    hhmm: str,
) -> str:
    """Текст макета: «{Место}: расписание изменилось» / убрали / добавили / «С сайта катка, HH:MM»."""
    lines = [f"<b>{html.escape(place_name)}: расписание изменилось</b>"]
    for day, group in _by_day(removed):
        times = [_minute(slot.starts_at_local).strftime("%H:%M") for slot in group]
        word = "сеанс" if len(times) == 1 else "сеансы"
        lines.append(f"{_WD_CAP[day.weekday()]}: убрали {word} {_join_ru(times)}.")
    removal_days = {slot.local_date for slot in removed}
    addition_days = {slot.local_date for slot in added}
    omit_day = bool(removed) and removal_days == addition_days and len(addition_days) == 1
    if omit_day:
        lines.append(f"Добавили {_join_ru([_range_label(slot) for slot in _by_day(added)[0][1]])}.")
    else:
        for day, group in _by_day(added):
            lines.append(f"{_WD_CAP[day.weekday()]}: добавили {_join_ru([_range_label(s) for s in group])}.")
    lines.append(f"С сайта катка, {hhmm}")
    return "\n".join(lines)


def format_reopened_html(place_name: str, slots: Sequence[FollowSlot]) -> str:
    """«Каток {место} открылся» и хвост макета. Времена — как «суббота 15:00 и 18:00»."""
    shown = sorted(slots, key=lambda slot: (slot.local_date, _minute(slot.starts_at_local)))[:4]
    parts: list[str] = []
    prev: date | None = None
    for slot in shown:
        hh = _minute(slot.starts_at_local).strftime("%H:%M")
        if prev is None or slot.local_date != prev:
            parts.append(f"{_WD_LOW[slot.local_date.weekday()]} {hh}")
        else:
            parts.append(hh)
        prev = slot.local_date
    sessions = f"Первые сеансы: {_join_ru(parts)}." if parts else "Первые сеансы появились в расписании."
    title = f"<b>Каток {html.escape(place_name)} открылся</b>"
    return f"{title}\n{sessions}\n{OPENING_TAIL}"


def slot_to_json(slot: FollowSlot) -> dict[str, str]:
    return {
        "local_date": slot.local_date.isoformat(),
        "starts_at_local": _minute(slot.starts_at_local).strftime("%H:%M"),
        "ends_at_local": _minute(slot.ends_at_local).strftime("%H:%M"),
        "kind": slot.kind,
    }


def slot_from_json(raw: Mapping[str, Any]) -> FollowSlot:
    start = time.fromisoformat(str(raw["starts_at_local"]))
    end = time.fromisoformat(str(raw["ends_at_local"]))
    return FollowSlot(
        local_date=date.fromisoformat(str(raw["local_date"])),
        starts_at_local=start,
        ends_at_local=end,
        kind=str(raw["kind"]),
    )


def net_slots(removed: Sequence[FollowSlot], added: Sequence[FollowSlot]) -> tuple[list[FollowSlot], list[FollowSlot]]:
    """Слот, который убрали и тут же вернули, из сообщения выпадает."""
    removed_by = {slot.key: slot for slot in removed}
    added_by = {slot.key: slot for slot in added}
    overlap = removed_by.keys() & added_by.keys()
    for key in overlap:
        removed_by.pop(key, None)
        added_by.pop(key, None)
    return list(removed_by.values()), list(added_by.values())


def _rows_to_slots(rows: Iterable[Any]) -> dict[tuple[date, time, str], FollowSlot]:
    indexed: dict[tuple[date, time, str], FollowSlot] = {}
    for row in rows:
        slot = FollowSlot(
            local_date=row[0],
            starts_at_local=row[1],
            ends_at_local=row[2],
            kind=str(row[3]),
        )
        indexed[slot.key] = slot
    return indexed


async def arena_has_active_follows(session: AsyncSession, arena_id: int) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1 FROM arena_follows
                WHERE arena_id = :arena AND muted_at IS NULL
                LIMIT 1
                """
            ),
            {"arena": int(arena_id)},
        )
    ).first()
    return row is not None


async def load_follow_window(
    session: AsyncSession,
    arena_id: int,
    *,
    now: datetime,
    today: date,
) -> dict[tuple[date, time, str], FollowSlot]:
    until = today + timedelta(days=FOLLOW_HORIZON_DAYS)
    rows = await session.execute(
        text(
            f"""
            SELECT local_date, starts_at_local, ends_at_local, kind
            FROM ice_sessions
            WHERE arena_id = :arena
              AND kind IN {_KINDS_SQL}
              AND schedule_basis IN {_BASIS_SQL}
              AND status = 'active'
              AND ends_at_utc > :now
              AND local_date >= :today
              AND local_date < :until
            """
        ),
        {"arena": int(arena_id), "now": _aware(now), "today": today, "until": until},
    )
    return _rows_to_slots(rows)


async def load_last_past_end(session: AsyncSession, arena_id: int, *, now: datetime) -> datetime | None:
    value = (
        await session.execute(
            text(
                f"""
                SELECT MAX(ends_at_utc) FROM ice_sessions
                WHERE arena_id = :arena
                  AND kind IN {_KINDS_SQL}
                  AND schedule_basis IN {_BASIS_SQL}
                  AND status = 'active'
                  AND ends_at_utc <= :now
                """
            ),
            {"arena": int(arena_id), "now": _aware(now)},
        )
    ).scalar()
    return _aware(value) if isinstance(value, datetime) else None


async def _active_follows(session: AsyncSession, arena_id: int) -> list[tuple[int, int]]:
    rows = await session.execute(
        text(
            """
            SELECT id, telegram_id FROM arena_follows
            WHERE arena_id = :arena AND muted_at IS NULL
            ORDER BY id
            """
        ),
        {"arena": int(arena_id)},
    )
    return [(int(row[0]), int(row[1])) for row in rows]


async def _arena_meta(session: AsyncSession, arena_id: int) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(
                """
                SELECT a.name, c.name AS city_name, p.timezone, p.slug
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.id = :id
                """
            ),
            {"id": int(arena_id)},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


def _place_name(meta: Mapping[str, Any] | None) -> str:
    if not meta:
        return "Каток"
    return str(meta.get("name") or "").strip() or "Каток"


async def _last_schedule_sent_at(session: AsyncSession, follow_id: int) -> datetime | None:
    value = (
        await session.execute(
            text(
                """
                SELECT MAX(sent_at) FROM arena_follow_notifications
                WHERE follow_id = :fid AND kind = :kind AND status = 'sent'
                """
            ),
            {"fid": int(follow_id), "kind": KIND_SCHEDULE},
        )
    ).scalar()
    return _aware(value) if isinstance(value, datetime) else None


async def _pending(session: AsyncSession, follow_id: int, kind: str):
    return (
        await session.execute(
            text(
                """
                SELECT id, payload, created_at, not_before
                FROM arena_follow_notifications
                WHERE follow_id = :fid AND kind = :kind AND status = 'pending'
                FOR UPDATE
                """
            ),
            {"fid": int(follow_id), "kind": kind},
        )
    ).mappings().first()


async def _upsert_pending(
    session: AsyncSession,
    *,
    follow_id: int,
    kind: str,
    payload: dict[str, Any],
    not_before: datetime,
    created_at: datetime,
) -> None:
    existing = await _pending(session, follow_id, kind)
    if existing is not None and kind == KIND_REOPENED:
        old = _as_dict(existing["payload"])
        if old.get("keep") is True or str(old.get("keep") or "").lower() == "true":
            payload = {**payload, "keep": True}
    body = json.dumps(payload, ensure_ascii=False)
    if existing is None:
        await session.execute(
            text(
                """
                INSERT INTO arena_follow_notifications
                    (follow_id, kind, payload, not_before, status, created_at)
                VALUES
                    (:fid, :kind, CAST(:payload AS jsonb), :not_before, 'pending', :created_at)
                """
            ),
            {
                "fid": int(follow_id),
                "kind": kind,
                "payload": body,
                "not_before": _aware(not_before),
                "created_at": _aware(created_at),
            },
        )
        return
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET payload = CAST(:payload AS jsonb),
                not_before = :not_before
            WHERE id = :id
            """
        ),
        {"payload": body, "not_before": _aware(not_before), "id": int(existing["id"])},
    )


async def _enqueue_schedule(
    session: AsyncSession,
    *,
    arena_id: int,
    followers: Sequence[tuple[int, int]],
    removed: Sequence[FollowSlot],
    added: Sequence[FollowSlot],
    now: datetime,
    meta: Mapping[str, Any],
) -> int:
    removed, added = net_slots(removed, added)
    if not removed and not added:
        return 0
    name = _place_name(meta)
    hhmm = _hhmm(now, str(meta.get("timezone") or "") or None)
    queued = 0
    for follow_id, _telegram_id in followers:
        existing = await _pending(session, follow_id, KIND_SCHEDULE)
        if existing is not None:
            old = _as_dict(existing["payload"])
            old_removed = [slot_from_json(item) for item in old.get("removed") or []]
            old_added = [slot_from_json(item) for item in old.get("added") or []]
            merged_removed, merged_added = net_slots([*old_removed, *removed], [*old_added, *added])
            if not merged_removed and not merged_added:
                await session.execute(
                    text("DELETE FROM arena_follow_notifications WHERE id = :id"),
                    {"id": int(existing["id"])},
                )
                continue
            batch_started = existing["created_at"]
            last_sent = await _last_schedule_sent_at(session, follow_id)
            not_before = schedule_not_before(
                now=now, batch_started_at=_aware(batch_started), last_sent_at=last_sent
            )
            payload = {
                "removed": [slot_to_json(slot) for slot in merged_removed],
                "added": [slot_to_json(slot) for slot in merged_added],
                "hhmm": hhmm,
                "text": format_schedule_changed_html(name, merged_removed, merged_added, hhmm),
            }
            await session.execute(
                text(
                    """
                    UPDATE arena_follow_notifications
                    SET payload = CAST(:payload AS jsonb), not_before = :not_before
                    WHERE id = :id
                    """
                ),
                {
                    "payload": json.dumps(payload, ensure_ascii=False),
                    "not_before": not_before,
                    "id": int(existing["id"]),
                },
            )
        else:
            last_sent = await _last_schedule_sent_at(session, follow_id)
            not_before = schedule_not_before(now=now, batch_started_at=_aware(now), last_sent_at=last_sent)
            payload = {
                "removed": [slot_to_json(slot) for slot in removed],
                "added": [slot_to_json(slot) for slot in added],
                "hhmm": hhmm,
                "text": format_schedule_changed_html(name, removed, added, hhmm),
            }
            await _upsert_pending(
                session,
                follow_id=follow_id,
                kind=KIND_SCHEDULE,
                payload=payload,
                not_before=not_before,
                created_at=_aware(now),
            )
        queued += 1
    if queued:
        logger.info("arena follow schedule queued arena=%s follows=%s", arena_id, queued)
    return queued


async def _enqueue_reopened(
    session: AsyncSession,
    *,
    arena_id: int,
    followers: Sequence[tuple[int, int]],
    slots: Sequence[FollowSlot],
    now: datetime,
    meta: Mapping[str, Any],
) -> int:
    if not slots:
        return 0
    name = _place_name(meta)
    text_html = format_reopened_html(name, slots)
    payload = {
        "slots": [slot_to_json(slot) for slot in slots],
        "text": text_html,
        "keep": False,
    }
    not_before = opening_not_before(now=now)
    queued = 0
    for follow_id, _telegram_id in followers:
        await _upsert_pending(
            session,
            follow_id=follow_id,
            kind=KIND_REOPENED,
            payload=payload,
            not_before=not_before,
            created_at=_aware(now),
        )
        queued += 1
    if queued:
        logger.info("arena follow reopen queued arena=%s follows=%s", arena_id, queued)
    return queued


async def record_publish_follow_diff(
    session: AsyncSession,
    *,
    arena_id: int,
    before: Mapping[tuple[date, time, str], FollowSlot],
    after: Mapping[tuple[date, time, str], FollowSlot],
    past_ended_at: datetime | None,
    now: datetime,
) -> int:
    """Поставить уведомления по дифу. Не коммитит — живёт в транзакции публикации."""
    removed_keys = before.keys() - after.keys()
    added_keys = after.keys() - before.keys()
    if not removed_keys and not added_keys:
        return 0
    followers = await _active_follows(session, arena_id)
    if not followers:
        return 0
    meta = await _arena_meta(session, arena_id)
    if meta is None:
        return 0
    if not before and added_keys:
        if past_ended_at is None:
            return 0
        if _aware(now) - _aware(past_ended_at) >= REOPEN_GAP:
            return await _enqueue_reopened(
                session,
                arena_id=arena_id,
                followers=followers,
                slots=list(after.values()),
                now=now,
                meta=meta,
            )
    return await _enqueue_schedule(
        session,
        arena_id=arena_id,
        followers=followers,
        removed=[before[key] for key in removed_keys],
        added=[after[key] for key in added_keys],
        now=now,
        meta=meta,
    )


async def enqueue_arena_reopened(
    session: AsyncSession,
    arena_id: int,
    *,
    now: datetime | None = None,
) -> int:
    """``season_closed`` → ``auto`` и на арене уже есть будущие сеансы массового катания."""
    moment = _aware(now or datetime.now(timezone.utc))
    meta = await _arena_meta(session, arena_id)
    if meta is None:
        return 0
    today = moment.astimezone(_tz(str(meta.get("timezone") or "") or None)).date()
    window = await load_follow_window(session, arena_id, now=moment, today=today)
    if not window:
        return 0
    followers = await _active_follows(session, arena_id)
    if not followers:
        return 0
    return await _enqueue_reopened(
        session,
        arena_id=arena_id,
        followers=followers,
        slots=list(window.values()),
        now=moment,
        meta=meta,
    )


def _buttons_for(kind: str, arena_id: int, url: str | None) -> tuple[FollowButton, ...]:
    buttons: list[FollowButton] = []
    if kind == KIND_REOPENED:
        if url:
            buttons.append(FollowButton(text=BTN_SCHEDULE, web_app_url=url))
        buttons.append(FollowButton(text=BTN_KEEP, callback_data=f"{CB_KEEP_PREFIX}{arena_id}"))
    else:
        if url:
            buttons.append(FollowButton(text=BTN_OPEN_SCHEDULE, web_app_url=url))
        buttons.append(FollowButton(text=BTN_UNFOLLOW, callback_data=f"{CB_UNFOLLOW_PREFIX}{arena_id}"))
    return tuple(buttons)


def _render_claimed(kind: str, payload: Mapping[str, Any], place_name: str) -> str:
    if kind == KIND_REOPENED:
        slots = [slot_from_json(item) for item in payload.get("slots") or []]
        return format_reopened_html(place_name, slots)
    removed = [slot_from_json(item) for item in payload.get("removed") or []]
    added = [slot_from_json(item) for item in payload.get("added") or []]
    hhmm = str(payload.get("hhmm") or "")
    return format_schedule_changed_html(place_name, removed, added, hhmm)


async def dispatch_due_follow_notifications(
    session: AsyncSession,
    *,
    now: datetime,
    webapp_base_url: str,
    send,
) -> int:
    """Забрать due-строки и отправить. ``send`` получает :class:`FollowOutbound`.

    ``FollowBotBlocked`` глушит подписку. Прочая ошибка возвращает строку в очередь.
    """
    moment = _aware(now)
    if not within_follow_hours(moment):
        return 0
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET status = 'pending'
            WHERE status = 'sending'
            """
        )
    )
    id_rows = (
        await session.execute(
            text(
                """
                SELECT n.id
                FROM arena_follow_notifications n
                JOIN arena_follows f ON f.id = n.follow_id
                WHERE n.status = 'pending'
                  AND n.not_before <= :now
                  AND f.muted_at IS NULL
                ORDER BY CASE WHEN n.kind = 'reopened' THEN 0 ELSE 1 END, n.id
                LIMIT 30
                FOR UPDATE OF n SKIP LOCKED
                """
            ),
            {"now": moment},
        )
    ).scalars().all()
    if not id_rows:
        await session.commit()
        return 0
    ids = [int(item) for item in id_rows]
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET status = 'sending', attempts = attempts + 1
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": ids},
    )
    claimed_rows = (
        await session.execute(
            text(
                """
                SELECT n.id, n.follow_id, n.kind, n.payload, n.attempts,
                       f.telegram_id, f.arena_id, f.muted_at,
                       a.name, c.name AS city_name, p.slug
                FROM arena_follow_notifications n
                JOIN arena_follows f ON f.id = n.follow_id
                JOIN arenas a ON a.id = f.arena_id
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE n.id = ANY(:ids)
                """
            ),
            {"ids": ids},
        )
    ).mappings().all()
    await session.commit()

    by_follow: dict[int, list[FollowOutbound]] = {}
    order: list[int] = []
    for row in claimed_rows:
        payload = _as_dict(row["payload"])
        place = str(row["name"] or "").strip() or "Каток"
        url = https_place_page_url(
            base_url=webapp_base_url,
            city_name=str(row["city_name"] or ""),
            slug=str(row["slug"]) if row["slug"] else None,
        )
        item = FollowOutbound(
            notification_id=int(row["id"]),
            follow_id=int(row["follow_id"]),
            telegram_id=int(row["telegram_id"]),
            arena_id=int(row["arena_id"]),
            kind=str(row["kind"]),
            text=_render_claimed(str(row["kind"]), payload, place),
            buttons=_buttons_for(str(row["kind"]), int(row["arena_id"]), url),
            attempts=int(row["attempts"] or 0),
        )
        if item.follow_id not in by_follow:
            order.append(item.follow_id)
        by_follow.setdefault(item.follow_id, []).append(item)

    sent = 0
    for follow_id in order:
        items = sorted(
            by_follow[follow_id],
            key=lambda item: (0 if item.kind == KIND_REOPENED else 1, item.notification_id),
        )
        primary, *rest = items
        if primary.attempts > MAX_SEND_ATTEMPTS:
            await _mark_failed(session, primary.notification_id)
            for extra in rest:
                await _release_sending(session, extra.notification_id, not_before=moment)
            await session.commit()
            continue
        still = (
            await session.execute(
                text(
                    """
                    SELECT 1 FROM arena_follows
                    WHERE id = :fid AND muted_at IS NULL
                    """
                ),
                {"fid": follow_id},
            )
        ).first()
        if still is None:
            await _mark_status(session, primary.notification_id, "muted")
            for extra in rest:
                await _mark_status(session, extra.notification_id, "muted")
            await session.commit()
            continue
        try:
            await send(primary)
        except FollowBotBlocked:
            await _mute_follow(session, follow_id, moment)
            await _mark_status(session, primary.notification_id, "muted")
            for extra in rest:
                await _mark_status(session, extra.notification_id, "muted")
        except Exception:
            logger.exception("arena follow notify failed id=%s", primary.notification_id)
            await _release_sending(
                session,
                primary.notification_id,
                not_before=moment + timedelta(seconds=min(60 * primary.attempts, 900)),
            )
            for extra in rest:
                await _release_sending(session, extra.notification_id, not_before=moment)
        else:
            await _mark_sent(session, primary, moment)
            for extra in rest:
                await _release_sending(session, extra.notification_id, not_before=moment + MIN_GAP)
            sent += 1
        await session.commit()
    return sent


async def _mark_status(session: AsyncSession, notification_id: int, status: str) -> None:
    await session.execute(
        text("UPDATE arena_follow_notifications SET status = :status WHERE id = :id"),
        {"status": status, "id": int(notification_id)},
    )


async def _mark_failed(session: AsyncSession, notification_id: int) -> None:
    await _mark_status(session, notification_id, "failed")


async def _release_sending(session: AsyncSession, notification_id: int, *, not_before: datetime) -> None:
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET status = 'pending', not_before = :not_before
            WHERE id = :id AND status = 'sending'
            """
        ),
        {"id": int(notification_id), "not_before": _aware(not_before)},
    )


async def _mute_follow(session: AsyncSession, follow_id: int, moment: datetime) -> None:
    await session.execute(
        text("UPDATE arena_follows SET muted_at = :now WHERE id = :id AND muted_at IS NULL"),
        {"now": moment, "id": int(follow_id)},
    )


async def _mark_sent(session: AsyncSession, item: FollowOutbound, moment: datetime) -> None:
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET status = 'sent', sent_at = :now
            WHERE id = :id
            """
        ),
        {"now": moment, "id": item.notification_id},
    )
    if item.kind == KIND_REOPENED:
        await session.execute(
            text(
                """
                UPDATE arena_follows
                SET muted_at = :now
                WHERE id = :fid
                  AND muted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM arena_follow_notifications n
                      WHERE n.follow_id = arena_follows.id
                        AND n.kind = 'reopened'
                        AND COALESCE(n.payload->>'keep', '') = 'true'
                  )
                """
            ),
            {"now": moment, "fid": item.follow_id},
        )
    await record_catalog_consumer_event(
        session,
        kind=KIND_FOLLOW_NOTIFIED,
        surface=SURFACE_ARENA_FOLLOW,
        actor_hash=telegram_actor_hash(item.telegram_id),
        arena_id=item.arena_id,
        payload={"notification_kind": item.kind, "notification_id": item.notification_id},
        dedup=False,
    )
