"""Client ice watch subscriptions and their reminders.

TASK-328: reminders for ``sessions`` watches are sent by one pass over all active watches
(``deliver_ice_watch_reminders``), which the ingest loop runs after the tick has committed,
under the cluster ingest lock. Nothing else sends them: not the ingest tick, not the API.
"""

from __future__ import annotations

import asyncio
import logging
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_profile import is_in_season
from src.application.client_ice_watch_filters import filter_label, session_matches_filter
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.ice_watch_message import OPEN_SCHEDULE_BUTTON, compose_new_schedule_message
from src.infrastructure.db.models import (
    ICE_WATCH_DEACTIVATED_FAILED,
    ICE_WATCH_DEACTIVATED_UNREACHABLE,
    ICE_WATCH_KIND_SCHEDULE_FRESH,
    ICE_WATCH_KIND_SEASON_OPEN,
    ICE_WATCH_KIND_SESSIONS,
)
from src.infrastructure.repositories.client_ice_watch_repository import ClientIceWatchRepository
from src.infrastructure.repositories.client_trainer_edge_repository import ClientTrainerEdgeRepository

logger = logging.getLogger(__name__)

MINSK_TZ = ZoneInfo("Europe/Minsk")

# Виды подписки, которые ждут нового расписания: их шлёт проход доставки (TASK-328).
# schedule_fresh кнопки в UI не имеет; держим его на тех же правилах, что и sessions,
# чтобы у вида остался ровно один отправитель.
_DELIVERY_KINDS = (ICE_WATCH_KIND_SESSIONS, ICE_WATCH_KIND_SCHEDULE_FRESH)
_PUBLIC_KINDS_SQL = "('public_skate', 'open_ice')"

# После стольких неудачных попыток подряд подписка гаснет с причиной failed.
MAX_DELIVERY_FAILURES = 5
# Отправка, которая висит дольше, считается неудачной попыткой: проход идёт под локом ингеста.
SEND_TIMEOUT_S = 20.0


class IceWatchChannelUnsupported(Exception):
    """Подписчику некуда доставить напоминание (MAX: нет чата Telegram)."""

_MONTHS_PREP = (
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
)

SendFn = Callable[[int, str, Any], Awaitable[None]]

# «на площадь» не склоняется. Префикс адреса → предложный падеж.
_ON_PLACE = (
    ("площадь ", "на площади "),
    ("проспект ", "на проспекте "),
    ("пр-т ", "на проспекте "),
    ("пр. ", "на проспекте "),
    ("улица ", "на улице "),
    ("ул. ", "на улице "),
    ("бульвар ", "на бульваре "),
)


def _on_place(address: str) -> str:
    """«площадь Ленина» → «на площади Ленина». Незнакомый адрес оставляем как есть."""
    raw = address.strip()
    folded = raw.lower()
    for prefix, prep in _ON_PLACE:
        if folded.startswith(prefix):
            return prep + raw[len(prefix) :]
    return raw


async def subscribe_ice_watch(
    session: AsyncSession,
    *,
    client_id: int,
    telegram_id: int,
    arena_id: int,
    watch_kind: str,
    filter_json: dict[str, Any] | None,
    city_id: int | None,
) -> dict[str, Any]:
    if watch_kind not in (ICE_WATCH_KIND_SESSIONS, ICE_WATCH_KIND_SCHEDULE_FRESH, ICE_WATCH_KIND_SEASON_OPEN):
        raise ValueError("invalid watch_kind")
    if int(telegram_id) <= 0:
        # MAX/VK: отрицательный суррогатный ключ, чата Telegram нет, а своего канала
        # доставки в MAX у нас нет — подписка была бы обещанием, которое не выполнить.
        raise IceWatchChannelUnsupported()
    baseline = None
    if watch_kind in _DELIVERY_KINDS:
        baseline = await future_sessions_horizon(session, arena_id)
    repo = ClientIceWatchRepository(session)
    row = await repo.upsert(
        client_id=client_id,
        telegram_id=telegram_id,
        arena_id=arena_id,
        watch_kind=watch_kind,
        filter_json=filter_json or {},
        city_id=city_id,
        baseline_horizon_date=baseline,
    )
    await session.commit()
    return await enrich_watch_row(session, row)


async def unsubscribe_ice_watch(
    session: AsyncSession,
    *,
    client_id: int,
    watch_id: int,
) -> dict[str, Any] | None:
    repo = ClientIceWatchRepository(session)
    row = await repo.deactivate(client_id, watch_id)
    await session.commit()
    return await enrich_watch_row(session, row) if row else None


async def list_ice_watches_for_client(session: AsyncSession, client_id: int) -> list[dict[str, Any]]:
    repo = ClientIceWatchRepository(session)
    rows = await repo.list_active_for_client(client_id)
    out = []
    for row in rows:
        out.append(await enrich_watch_row(session, row))
    return out


async def count_trainer_slot_watches(session: AsyncSession, client_id: int) -> int:
    r = await session.execute(
        text(
            """
            SELECT COUNT(*)::int
            FROM client_trainer_edges
            WHERE client_id = :cid AND notify_when_slots = true
            """
        ),
        {"cid": client_id},
    )
    return int(r.scalar() or 0)


async def watches_summary(session: AsyncSession, client_id: int) -> dict[str, Any]:
    ice_repo = ClientIceWatchRepository(session)
    ice_n = await ice_repo.count_active_for_client(client_id)
    trainer_n = await count_trainer_slot_watches(session, client_id)
    return {
        "active_count": ice_n + trainer_n,
        "trainer_slot_watches": trainer_n,
        "ice_watches": ice_n,
    }


async def client_watches_hub_payload(session: AsyncSession, client_id: int) -> dict[str, Any]:
    summary = await watches_summary(session, client_id)
    ice = await list_ice_watches_for_client(session, client_id)
    trainer_rows = await _trainer_slot_watch_rows(session, client_id)
    return {
        **summary,
        "trainer_notifications": trainer_rows,
        "ice_watch_items": ice,
    }


async def _trainer_slot_watch_rows(session: AsyncSession, client_id: int) -> list[dict[str, Any]]:
    r = await session.execute(
        text(
            """
            SELECT e.trainer_id, e.notify_when_slots_at,
                   COALESCE(NULLIF(TRIM(COALESCE(tp.first_name, '') || ' ' || COALESCE(tp.last_name, '')), ''), 'Тренер')
            FROM client_trainer_edges e
            JOIN trainers t ON t.id = e.trainer_id
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = t.id
            WHERE e.client_id = :cid AND e.notify_when_slots = true
            ORDER BY e.notify_when_slots_at DESC NULLS LAST
            """
        ),
        {"cid": client_id},
    )
    out = []
    for row in r.fetchall():
        out.append(
            {
                "kind": "trainer_slots",
                "trainer_id": int(row[0]),
                "subscribed_at": row[1].isoformat() if row[1] else None,
                "arena_id": None,
                "arena_name": None,
                "title": str(row[2]),
                "filter_label": "Свободные окна",
                "status_label": "Ждём новые слоты · разовое",
            }
        )
    return out


async def enrich_watch_row(session: AsyncSession, row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    aid = int(row["arena_id"])
    r = await session.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(a.name), ''), 'Каток'), p.season_start_month
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :aid
            """
        ),
        {"aid": aid},
    )
    arena_row = r.fetchone()
    arena_name = str(arena_row[0] if arena_row else "Каток")
    season_start = arena_row[1] if arena_row else None
    kind = str(row["watch_kind"])
    fl = filter_label(row.get("filter_json"))
    if kind == ICE_WATCH_KIND_SESSIONS:
        status = "Ждём сеансы"
    elif kind == ICE_WATCH_KIND_SCHEDULE_FRESH:
        status = "Ждём обновление расписания"
    elif kind == ICE_WATCH_KIND_SEASON_OPEN:
        fl = "Начало сезона"
        month = int(season_start) if season_start else None
        if month and 1 <= month <= 12:
            status = f"Напомним в {_MONTHS_PREP[month - 1]}"
        else:
            status = "Напомним о начале сезона"
    else:
        status = ""
    return {
        "id": int(row["id"]),
        "kind": kind,
        "arena_id": aid,
        "arena_name": arena_name,
        "city_id": row.get("city_id"),
        "filter": row.get("filter_json") or {},
        "filter_label": fl,
        "status_label": status,
        "subscribed_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


async def _load_future_sessions(
    session: AsyncSession,
    arena_id: int,
    *,
    now: datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    r = await session.execute(
        text(
            """
            SELECT id, starts_at_utc, starts_at_local, local_date, kind
            FROM ice_sessions
            WHERE arena_id = :aid
              AND status = :st
              AND starts_at_utc > :now
              AND kind IN ('public_skate', 'open_ice')
            ORDER BY starts_at_utc ASC
            LIMIT :limit
            """
        ),
        {"aid": arena_id, "st": STATUS_ACTIVE, "now": now, "limit": limit},
    )
    keys = ("id", "starts_at_utc", "starts_at_local", "local_date", "kind")
    return [dict(zip(keys, row)) for row in r.fetchall()]


def compose_season_open_telegram_message(
    *,
    arena_name: str,
    address: str | None,
    season_start_month: int,
    has_phone: bool,
) -> str:
    """One-shot calendar reminder. Does not claim the ice is already poured."""
    month_prep = _MONTHS_PREP[int(season_start_month) - 1]
    safe_name = html.escape(arena_name.strip() or "Каток")
    lines = [
        "<b>Пора проверять коньки</b>",
        f"\n«{safe_name}» обычно открывается в {month_prep}",
    ]
    addr = (address or "").strip()
    if addr:
        lines.append(f" — {html.escape(_on_place(addr))}.")
    else:
        lines.append(".")
    if has_phone:
        lines.append(
            "\nЛёд заливают по погоде. На карточке есть телефон: "
            "один звонок, и не приедете кататься по луже."
        )
    else:
        lines.append(
            "\nЛёд заливают по погоде. Перед поездкой лучше убедиться, что уже залили — "
            "лужа коньков не любит."
        )
    return "".join(lines)


async def _load_arena_season_notify_fields(session: AsyncSession, arena_id: int) -> dict[str, Any] | None:
    r = await session.execute(
        text(
            """
            SELECT
                COALESCE(NULLIF(TRIM(a.name), ''), 'Каток'),
                NULLIF(TRIM(a.address), ''),
                NULLIF(TRIM(p.phone), ''),
                p.season_start_month,
                p.season_end_month
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :aid
            """
        ),
        {"aid": arena_id},
    )
    row = r.fetchone()
    if row is None:
        return None
    return {
        "arena_name": str(row[0]),
        "address": row[1],
        "phone": row[2],
        "season_start_month": row[3],
        "season_end_month": row[4],
    }


def _minsk_month(now: datetime) -> int:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(MINSK_TZ).month


async def notify_season_open_watches(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    send_fn: SendFn,
    reply_markup_factory: Callable[[int], Any] | None = None,
) -> int:
    """Send season_open watches once in ``season_start_month`` (Europe/Minsk)."""
    repo = ClientIceWatchRepository(session)
    watches = await repo.list_active_by_kind(ICE_WATCH_KIND_SEASON_OPEN)
    if not watches:
        return 0

    now = now or datetime.now(timezone.utc)
    month = _minsk_month(now)
    by_arena: dict[int, list[dict[str, Any]]] = {}
    for watch in watches:
        by_arena.setdefault(int(watch["arena_id"]), []).append(watch)

    sent = 0
    changed = False
    for arena_id, arena_watches in by_arena.items():
        arena = await _load_arena_season_notify_fields(session, arena_id)
        if arena is None:
            continue
        start = arena.get("season_start_month")
        end = arena.get("season_end_month")
        if start is None or end is None:
            for watch in arena_watches:
                await repo.mark_notified_and_deactivate(int(watch["id"]))
                changed = True
            continue

        start_i = int(start)
        end_i = int(end)
        if month != start_i:
            if is_in_season(start_i, end_i, month):
                for watch in arena_watches:
                    await repo.mark_notified_and_deactivate(int(watch["id"]))
                    changed = True
            continue

        sessions = await _load_future_sessions(session, arena_id)
        if sessions:
            n = await repo.deactivate_active_for_arena_kind(arena_id, ICE_WATCH_KIND_SEASON_OPEN)
            if n:
                changed = True
            continue

        has_phone = bool(str(arena.get("phone") or "").strip())
        text_msg = compose_season_open_telegram_message(
            arena_name=str(arena["arena_name"]),
            address=str(arena["address"]) if arena.get("address") else None,
            season_start_month=start_i,
            has_phone=has_phone,
        )
        markup = reply_markup_factory(arena_id) if reply_markup_factory else None
        for watch in arena_watches:
            try:
                await send_fn(int(watch["telegram_id"]), text_msg, markup)
                await repo.mark_notified_and_deactivate(int(watch["id"]))
                sent += 1
                changed = True
            except Exception:
                logger.exception("season_open watch notify failed watch_id=%s", watch.get("id"))

    if changed:
        await session.commit()
    return sent


async def future_sessions_horizon(
    session: AsyncSession, arena_id: int, *, now: datetime | None = None
) -> date | None:
    """AC1: последняя ``local_date`` будущих публичных сеансов катка; ``None`` — их нет."""
    now = now or datetime.now(timezone.utc)
    r = await session.execute(
        text(
            f"""
            SELECT MAX(local_date)
            FROM ice_sessions
            WHERE arena_id = :aid
              AND status = :st
              AND starts_at_utc > :now
              AND kind IN {_PUBLIC_KINDS_SQL}
            """
        ),
        {"aid": int(arena_id), "st": STATUS_ACTIVE, "now": now},
    )
    return r.scalar()


@dataclass
class IceWatchPassStats:
    due: int = 0
    sent: int = 0
    failed: int = 0
    unreachable: int = 0
    gave_up: int = 0
    flood_limited: bool = False


class _FloodLimited(Exception):
    """Telegram ответил 429: остаток прохода откладываем, подписки не штрафуем."""


# Telegram: чат больше недоступен — повтор не поможет.
_UNREACHABLE_MARKERS = (
    "chat not found",
    "user not found",
    "peer_id_invalid",
    "user is deactivated",
    "bot was blocked",
    "bot was kicked",
    "have no access",
)
_LONG_NUMBER = re.compile(r"\d{5,}")


def is_unreachable_chat_error(exc: BaseException) -> bool:
    """Бот заблокирован, чат не найден, пользователь удалён."""
    if isinstance(exc, TelegramForbiddenError):
        return True
    if isinstance(exc, TelegramBadRequest):
        message = str(getattr(exc, "message", "") or exc).lower()
        return any(marker in message for marker in _UNREACHABLE_MARKERS)
    return False


def short_delivery_error(exc: BaseException) -> str:
    """Коротко для журнала: тип и текст ответа, без chat_id и прочих длинных чисел."""
    message = str(getattr(exc, "message", "") or exc).strip()
    message = _LONG_NUMBER.sub("…", message)
    label = type(exc).__name__
    return (f"{label}: {message}" if message else label)[:200]


def _new_sessions_for_watch(
    sessions: list[dict[str, Any]], watch: dict[str, Any], *, now: datetime
) -> list[dict[str, Any]]:
    """Будущие подходящие сеансы позже базы подписки (AC1). ``sessions`` — по времени начала."""
    baseline = watch.get("baseline_horizon_date")
    return [
        s
        for s in sessions
        if (baseline is None or s["local_date"] > baseline)
        and session_matches_filter(s, watch.get("filter_json"), now=now)
    ]


async def _arena_name_and_tz(session: AsyncSession, arena_id: int) -> tuple[str, ZoneInfo]:
    r = await session.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(a.name), ''), 'Каток'), NULLIF(TRIM(p.timezone), '')
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :aid
            """
        ),
        {"aid": int(arena_id)},
    )
    row = r.fetchone()
    name = str(row[0]) if row else "Каток"
    try:
        tz = ZoneInfo(str(row[1])) if row and row[1] else MINSK_TZ
    except Exception:  # noqa: BLE001 — кривая зона в профиле не должна ронять доставку
        tz = MINSK_TZ
    return name, tz


def _compose_for_new_sessions(
    arena_name: str, tz: ZoneInfo, new_sessions: list[dict[str, Any]], *, now: datetime
) -> str:
    dates = [s["local_date"] for s in new_sessions]
    nearest = new_sessions[0]
    return compose_new_schedule_message(
        arena_name=arena_name,
        first_date=min(dates),
        last_date=max(dates),
        nearest_date=nearest["local_date"],
        nearest_time=nearest["starts_at_local"],
        today=now.astimezone(tz).date(),
    )


async def _clear_season_open_where_sessions(session: AsyncSession, *, now: datetime) -> int:
    """Как раньше после публикации: у катка есть будущие сеансы — сезонное напоминание не нужно."""
    r = await session.execute(
        text(
            f"""
            UPDATE client_ice_watches w
            SET active = false
            WHERE w.active = true
              AND w.watch_kind = :kind
              AND EXISTS (
                  SELECT 1 FROM ice_sessions s
                  WHERE s.arena_id = w.arena_id
                    AND s.status = :st
                    AND s.starts_at_utc > :now
                    AND s.kind IN {_PUBLIC_KINDS_SQL}
              )
            """
        ),
        {"kind": ICE_WATCH_KIND_SEASON_OPEN, "st": STATUS_ACTIVE, "now": now},
    )
    return int(r.rowcount or 0)


async def deliver_ice_watch_reminders(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    send_fn: SendFn,
    reply_markup_factory: Callable[[int], Any] | None = None,
) -> IceWatchPassStats:
    """Один проход по всем активным подпискам на новое расписание (TASK-328).

    Семантика доставки — at-least-once: сначала отправка, затем в одной транзакции строка
    журнала и погашение подписки, коммит на каждую подписку. Сбой между отправкой и
    коммитом даёт ровно один повтор на следующем проходе; успешный коммит гасит подписку,
    поэтому дубля на каждом проходе нет. Потерять напоминание хуже, чем изредка повторить.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    repo = ClientIceWatchRepository(session)
    stats = IceWatchPassStats()

    if await _clear_season_open_where_sessions(session, now=now):
        await session.commit()

    watches = await repo.list_active_by_kinds(_DELIVERY_KINDS)
    sessions_by_arena: dict[int, list[dict[str, Any]]] = {}
    arena_info: dict[int, tuple[str, ZoneInfo]] = {}
    for watch in watches:
        arena_id = int(watch["arena_id"])
        if arena_id not in sessions_by_arena:
            sessions_by_arena[arena_id] = await _load_future_sessions(session, arena_id, now=now, limit=5000)
        new_sessions = _new_sessions_for_watch(sessions_by_arena[arena_id], watch, now=now)
        if not new_sessions:
            continue
        if arena_id not in arena_info:
            arena_info[arena_id] = await _arena_name_and_tz(session, arena_id)
        stats.due += 1
        name, tz = arena_info[arena_id]
        try:
            await _deliver_one(
                session,
                repo,
                watch,
                text_msg=_compose_for_new_sessions(name, tz, new_sessions, now=now),
                send_fn=send_fn,
                reply_markup_factory=reply_markup_factory,
                stats=stats,
            )
        except _FloodLimited:
            stats.flood_limited = True
            logger.warning(
                "ice watch delivery pass stopped by Telegram flood limit at watch_id=%s; rest goes next pass",
                watch.get("id"),
            )
            break
        except Exception:
            # Сбой учёта (БД) — откатываем только эту подписку; она останется активной и
            # пройдёт на следующем проходе. Остальные подписки не ждут.
            await session.rollback()
            logger.exception("ice watch delivery bookkeeping failed watch_id=%s", watch.get("id"))
    return stats


async def _deliver_one(
    session: AsyncSession,
    repo: ClientIceWatchRepository,
    watch: dict[str, Any],
    *,
    text_msg: str,
    send_fn: SendFn,
    reply_markup_factory: Callable[[int], Any] | None,
    stats: IceWatchPassStats,
) -> None:
    watch_id = int(watch["id"])
    # Лок строки до коммита: отписка из Mini App, пришедшая во время прохода, либо видна
    # здесь (и мы не шлём), либо ждёт нашего коммита.
    locked = await repo.lock_if_active(watch_id)
    if locked is None:
        await session.commit()
        return
    arena_id = int(locked["arena_id"])
    client_id = int(locked["client_id"])
    telegram_id = int(locked["telegram_id"])

    if telegram_id <= 0:
        await repo.record_delivery(
            watch_id=watch_id,
            client_id=client_id,
            arena_id=arena_id,
            attempted_at=datetime.now(timezone.utc),
            ok=False,
            error="channel_unsupported",
        )
        await repo.deactivate_with_reason(watch_id, ICE_WATCH_DEACTIVATED_UNREACHABLE)
        await session.commit()
        stats.unreachable += 1
        return

    markup = reply_markup_factory(arena_id) if reply_markup_factory else None
    attempted_at = datetime.now(timezone.utc)
    try:
        async with asyncio.timeout(SEND_TIMEOUT_S):
            await send_fn(telegram_id, text_msg, markup)
    except Exception as exc:  # noqa: BLE001 — любая ошибка отправки учитывается, не роняет проход
        error = short_delivery_error(exc)
        await repo.record_delivery(
            watch_id=watch_id,
            client_id=client_id,
            arena_id=arena_id,
            attempted_at=attempted_at,
            ok=False,
            error=error,
        )
        if isinstance(exc, TelegramRetryAfter):
            # Флуд-лимит — не вина подписки: failed_attempts не трогаем, проход прерываем.
            await session.commit()
            raise _FloodLimited() from exc
        if is_unreachable_chat_error(exc):
            await repo.deactivate_with_reason(watch_id, ICE_WATCH_DEACTIVATED_UNREACHABLE)
            stats.unreachable += 1
            logger.warning("ice watch chat unreachable watch_id=%s: %s", watch_id, error)
        else:
            failures = await repo.increment_failed_attempts(watch_id)
            if failures >= MAX_DELIVERY_FAILURES:
                await repo.deactivate_with_reason(watch_id, ICE_WATCH_DEACTIVATED_FAILED)
                stats.gave_up += 1
                logger.error(
                    "ice watch delivery gave up after %s failures watch_id=%s arena_id=%s: %s",
                    failures,
                    watch_id,
                    arena_id,
                    error,
                )
            else:
                stats.failed += 1
                logger.warning(
                    "ice watch delivery failed (%s/%s) watch_id=%s: %s",
                    failures,
                    MAX_DELIVERY_FAILURES,
                    watch_id,
                    error,
                )
        await session.commit()
        return

    await repo.record_delivery(
        watch_id=watch_id,
        client_id=client_id,
        arena_id=arena_id,
        attempted_at=attempted_at,
        ok=True,
    )
    await repo.mark_notified_and_deactivate(watch_id)
    await session.commit()
    stats.sent += 1


def _open_schedule_markup_factory(base_url: str) -> Callable[[int], Any]:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    base = (base_url or "").rstrip("/")

    def _markup(arena_id: int) -> InlineKeyboardMarkup:
        url = f"{base}/webapp/arena?arena_id={int(arena_id)}"
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=OPEN_SCHEDULE_BUTTON, web_app=WebAppInfo(url=url))]]
        )

    return _markup


async def run_ice_watch_delivery_pass(*, now: datetime | None = None) -> IceWatchPassStats:
    """Фоновая точка входа: своя сессия и клиентский бот (создаётся, только если есть что слать)."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.infrastructure.db.session import async_session_factory
    from src.shared.config import Settings

    settings = Settings()
    bot: Bot | None = None

    async def _send(tg_id: int, txt: str, markup=None) -> None:
        nonlocal bot
        if bot is None:
            bot = Bot(
                token=settings.telegram_bot_token_client,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
        await bot.send_message(chat_id=tg_id, text=txt, reply_markup=markup)

    try:
        async with async_session_factory() as session:
            return await deliver_ice_watch_reminders(
                session,
                now=now,
                send_fn=_send,
                reply_markup_factory=_open_schedule_markup_factory(settings.webapp_base_url or ""),
            )
    finally:
        if bot is not None:
            await bot.session.close()


async def run_season_open_watch_notifications() -> int:
    """Background entry: season_open watches for the current month (Europe/Minsk)."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    from src.infrastructure.db.session import async_session_factory
    from src.shared.config import Settings

    settings = Settings()
    base = (settings.webapp_base_url or "").rstrip("/")

    def _markup(aid: int) -> InlineKeyboardMarkup:
        url = f"{base}/webapp/arena?arena_id={aid}"
        return InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Открыть в ICING", web_app=WebAppInfo(url=url))]]
        )

    bot = Bot(
        token=settings.telegram_bot_token_client,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:

        async def _send(tg_id: int, txt: str, markup=None) -> None:
            await bot.send_message(chat_id=tg_id, text=txt, reply_markup=markup)

        async with async_session_factory() as session:
            return await notify_season_open_watches(
                session,
                send_fn=_send,
                reply_markup_factory=_markup,
            )
    finally:
        await bot.session.close()
