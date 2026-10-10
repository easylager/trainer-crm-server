"""Client ice watch subscriptions and post-ingest notifications."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_ice_watch_filters import filter_label, session_matches_filter
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.infrastructure.db.models import ICE_WATCH_KIND_SCHEDULE_FRESH, ICE_WATCH_KIND_SESSIONS
from src.infrastructure.repositories.client_ice_watch_repository import ClientIceWatchRepository
from src.infrastructure.repositories.client_trainer_edge_repository import ClientTrainerEdgeRepository

logger = logging.getLogger(__name__)

SendFn = Callable[[int, str, Any], Awaitable[None]]


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
    if watch_kind not in (ICE_WATCH_KIND_SESSIONS, ICE_WATCH_KIND_SCHEDULE_FRESH):
        raise ValueError("invalid watch_kind")
    repo = ClientIceWatchRepository(session)
    row = await repo.upsert(
        client_id=client_id,
        telegram_id=telegram_id,
        arena_id=arena_id,
        watch_kind=watch_kind,
        filter_json=filter_json or {},
        city_id=city_id,
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
        text("SELECT COALESCE(NULLIF(TRIM(name), ''), 'Каток') FROM arenas WHERE id = :aid"),
        {"aid": aid},
    )
    arena_name = str(r.scalar() or "Каток")
    kind = str(row["watch_kind"])
    fl = filter_label(row.get("filter_json"))
    status = "Ждём сеансы" if kind == ICE_WATCH_KIND_SESSIONS else "Ждём обновление расписания"
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


async def _load_future_sessions(session: AsyncSession, arena_id: int) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
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
            LIMIT 200
            """
        ),
        {"aid": arena_id, "st": STATUS_ACTIVE, "now": now},
    )
    keys = ("id", "starts_at_utc", "starts_at_local", "local_date", "kind")
    return [dict(zip(keys, row)) for row in r.fetchall()]


async def notify_ice_watches_after_arena_publish(
    session: AsyncSession,
    arena_id: int,
    *,
    send_fn: SendFn,
    reply_markup_factory: Callable[[int], Any] | None = None,
) -> int:
    """
    Called after a successful ice_sessions publish for ``arena_id``.
    One-shot: matching watches are deactivated after send.
    """
    repo = ClientIceWatchRepository(session)
    watches = await repo.list_active_for_arena(arena_id)
    if not watches:
        return 0

    sessions = await _load_future_sessions(session, arena_id)
    arena_name = (await enrich_watch_row(session, watches[0])).get("arena_name") or "Каток"
    sent = 0
    now = datetime.now(timezone.utc)

    for watch in watches:
        kind = str(watch["watch_kind"])
        try:
            if kind == ICE_WATCH_KIND_SCHEDULE_FRESH:
                text_msg = (
                    "↻ <b>Расписание обновлено</b>\n\n"
                    f"На <b>{arena_name}</b> снова есть актуальное расписание — "
                    "проверьте сеансы в приложении."
                )
                markup = reply_markup_factory(int(watch["arena_id"])) if reply_markup_factory else None
                await send_fn(int(watch["telegram_id"]), text_msg, markup)
                await repo.mark_notified_and_deactivate(int(watch["id"]))
                sent += 1
                continue

            if kind != ICE_WATCH_KIND_SESSIONS:
                continue
            matching = [
                s
                for s in sessions
                if session_matches_filter(s, watch.get("filter_json"), now=now)
            ]
            if not matching:
                continue
            top = matching[0]
            time_local = str(top.get("starts_at_local") or "")[:5]
            date_local = str(top.get("local_date") or "")
            extra = len(matching) - 1
            fl = filter_label(watch.get("filter_json"))
            lines = [
                "🧊 <b>Появились сеансы</b>\n",
                f"<b>{arena_name}</b> · {fl}",
            ]
            if date_local and time_local:
                lines.append(f"\nБлижайший: {date_local} {time_local}")
            if extra > 0:
                lines.append(f"\nИ ещё {extra} по вашему фильтру.")
            text_msg = "".join(lines)
            markup = reply_markup_factory(int(watch["arena_id"])) if reply_markup_factory else None
            await send_fn(int(watch["telegram_id"]), text_msg, markup)
            await repo.mark_notified_and_deactivate(int(watch["id"]))
            sent += 1
        except Exception:
            logger.exception("ice watch notify failed watch_id=%s", watch.get("id"))

    if sent:
        await session.commit()
    return sent


async def run_ice_watch_notifications_for_arena(arena_id: int) -> int:
    """Background entry: own session + client bot."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

    from src.shared.config import Settings
    from src.infrastructure.db.session import async_session_factory

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
            return await notify_ice_watches_after_arena_publish(
                session,
                int(arena_id),
                send_fn=_send,
                reply_markup_factory=_markup,
            )
    finally:
        await bot.session.close()
