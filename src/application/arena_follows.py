"""Подписка «следить за катком» (TASK-213): deep link, Mini App API, отписка.

Кнопки на /p/ и в карточке Mini App — TASK-211. Здесь только запись в БД и ответ бота.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    KIND_FOLLOW_CREATED,
    KIND_FOLLOW_REMOVED,
    SURFACE_ARENA_FOLLOW,
    record_catalog_consumer_event,
    telegram_actor_hash,
)
from src.application.place_links import is_valid_start_param, place_page_url
from src.shared.arena_schedule_mode import SCHEDULE_MODE_SEASON_CLOSED, normalize_schedule_mode
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, public_scope_params

FOLLOW_START_PREFIX = "follow_"
SOURCE_BOT_START = "bot_start"
SOURCE_MINIAPP = "miniapp"
FOLLOW_SOURCES = (SOURCE_BOT_START, SOURCE_MINIAPP)

BTN_SCHEDULE = "Расписание"
BTN_OPEN_SCHEDULE = "Открыть расписание"
BTN_UNFOLLOW = "Не следить"
BTN_KEEP = "Следить дальше"

CB_UNFOLLOW_PREFIX = "af:off:"
CB_KEEP_PREFIX = "af:on:"

FOLLOW_MISSING_TEXT = (
    "Не нашли такой каток. Откройте его страницу в Glide и нажмите «Следить» ещё раз."
)
_FOLLOW_RE = re.compile(r"^follow_([1-9][0-9]*)$")


@dataclass(frozen=True)
class FollowButton:
    text: str
    web_app_url: str | None = None
    callback_data: str | None = None


@dataclass(frozen=True)
class FollowChatReply:
    text: str
    buttons: tuple[FollowButton, ...] = ()
    found: bool = True
    created: bool = False
    arena_id: int | None = None
    arena_name: str | None = None


def looks_like_follow_start(payload: str | None) -> bool:
    return (payload or "").strip().startswith("follow")


def parse_follow_arena_id(payload: str | None) -> int | None:
    """``follow_42`` → 42. Длина и алфавит — ``is_valid_start_param`` (правила Telegram)."""
    raw = (payload or "").strip()
    if not is_valid_start_param(raw):
        return None
    match = _FOLLOW_RE.fullmatch(raw)
    if match is None:
        return None
    return int(match.group(1))


def parse_follow_callback_arena_id(data: str | None, prefix: str) -> int | None:
    raw = (data or "").strip()
    if not raw.startswith(prefix):
        return None
    rest = raw[len(prefix) :]
    if not rest.isdigit() or int(rest) <= 0:
        return None
    return int(rest)


def _schedule_buttons(arena_id: int, *, url: str | None, label: str) -> tuple[FollowButton, ...]:
    buttons: list[FollowButton] = []
    if url:
        buttons.append(FollowButton(text=label, web_app_url=url))
    buttons.append(FollowButton(text=BTN_UNFOLLOW, callback_data=f"{CB_UNFOLLOW_PREFIX}{int(arena_id)}"))
    return tuple(buttons)


def https_place_page_url(*, base_url: str, city_name: str, slug: str | None) -> str | None:
    if not slug or not city_name:
        return None
    url = place_page_url(base_url=base_url, city_name=city_name, slug=slug)
    if url.lower().startswith("https://"):
        return url
    return None


async def _metric(
    session: AsyncSession,
    *,
    kind: str,
    telegram_id: int,
    arena_id: int,
    payload: dict,
) -> None:
    city_id = (
        await session.execute(text("SELECT city_id FROM arenas WHERE id = :id"), {"id": int(arena_id)})
    ).scalar()
    await record_catalog_consumer_event(
        session,
        kind=kind,
        surface=SURFACE_ARENA_FOLLOW,
        actor_hash=telegram_actor_hash(telegram_id),
        city_id=int(city_id) if city_id is not None else None,
        arena_id=int(arena_id),
        payload=payload,
        dedup=False,
    )


async def _visible_arena(session: AsyncSession, arena_id: int):
    return (
        await session.execute(
            text(
                f"""
                SELECT a.id, a.name, c.name AS city_name, p.slug, p.schedule_mode
                FROM arenas a
                JOIN cities c ON c.id = a.city_id
                LEFT JOIN arena_profiles p ON p.arena_id = a.id
                WHERE a.id = :id AND {PUBLIC_ARENA_VISIBLE_SQL}
                """
            ),
            {"id": int(arena_id), **public_scope_params()},
        )
    ).mappings().first()


def _ready_text(name: str, *, season_closed: bool) -> str:
    extra = " или когда каток откроется" if season_closed else ""
    return f"Готово: следим за {html.escape(name)}. Напишем, если сеансы поменяются{extra}."


async def follow_arena(
    session: AsyncSession,
    *,
    telegram_id: int,
    arena_id: int,
    source: str,
    webapp_base_url: str = "",
) -> FollowChatReply:
    """Идемпотентная подписка. Повтор не создаёт вторую строку; заглушенная снова включается."""
    if source not in FOLLOW_SOURCES or int(telegram_id) <= 0 or int(arena_id) <= 0:
        return FollowChatReply(text=FOLLOW_MISSING_TEXT, found=False)
    arena = await _visible_arena(session, int(arena_id))
    if arena is None:
        return FollowChatReply(text=FOLLOW_MISSING_TEXT, found=False)
    name = str(arena["name"] or "").strip() or "каток"
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO arena_follows (telegram_id, arena_id, source)
                VALUES (:tg, :arena, :source)
                ON CONFLICT (telegram_id, arena_id) DO NOTHING
                RETURNING id
                """
            ),
            {"tg": int(telegram_id), "arena": int(arena_id), "source": source},
        )
    ).first()
    created = inserted is not None
    if created:
        await _metric(
            session,
            kind=KIND_FOLLOW_CREATED,
            telegram_id=int(telegram_id),
            arena_id=int(arena_id),
            payload={"source": source},
        )
    else:
        await session.execute(
            text(
                """
                UPDATE arena_follows
                SET muted_at = NULL
                WHERE telegram_id = :tg AND arena_id = :arena AND muted_at IS NOT NULL
                """
            ),
            {"tg": int(telegram_id), "arena": int(arena_id)},
        )
    await session.commit()
    closed = normalize_schedule_mode(arena["schedule_mode"]) == SCHEDULE_MODE_SEASON_CLOSED
    url = https_place_page_url(
        base_url=webapp_base_url,
        city_name=str(arena["city_name"] or ""),
        slug=str(arena["slug"]) if arena["slug"] else None,
    )
    return FollowChatReply(
        text=_ready_text(name, season_closed=closed),
        buttons=_schedule_buttons(int(arena_id), url=url, label=BTN_SCHEDULE),
        found=True,
        created=created,
        arena_id=int(arena_id),
        arena_name=name,
    )


async def open_follow_from_start(
    session: AsyncSession,
    *,
    telegram_id: int,
    payload: str,
    webapp_base_url: str = "",
) -> FollowChatReply:
    arena_id = parse_follow_arena_id(payload)
    if arena_id is None:
        return FollowChatReply(text=FOLLOW_MISSING_TEXT, found=False)
    return await follow_arena(
        session,
        telegram_id=telegram_id,
        arena_id=arena_id,
        source=SOURCE_BOT_START,
        webapp_base_url=webapp_base_url,
    )


async def _arena_label(session: AsyncSession, arena_id: int) -> str:
    name = (
        await session.execute(text("SELECT name FROM arenas WHERE id = :id"), {"id": int(arena_id)})
    ).scalar()
    return str(name or "").strip() or "этот каток"


async def unfollow_arena(
    session: AsyncSession,
    *,
    telegram_id: int,
    arena_id: int,
    via: str,
) -> FollowChatReply:
    name = await _arena_label(session, arena_id)
    deleted = (
        await session.execute(
            text(
                """
                DELETE FROM arena_follows
                WHERE telegram_id = :tg AND arena_id = :arena
                RETURNING id
                """
            ),
            {"tg": int(telegram_id), "arena": int(arena_id)},
        )
    ).first()
    if deleted is not None:
        await _metric(
            session,
            kind=KIND_FOLLOW_REMOVED,
            telegram_id=int(telegram_id),
            arena_id=int(arena_id),
            payload={"via": via},
        )
    await session.commit()
    if deleted is None:
        return FollowChatReply(text="Вы уже не следите за этим катком.", arena_id=int(arena_id))
    return FollowChatReply(
        text=f"Больше не следим за {html.escape(name)}.",
        arena_id=int(arena_id),
        arena_name=name,
    )


async def unfollow_command(session: AsyncSession, *, telegram_id: int) -> FollowChatReply:
    rows = (
        await session.execute(
            text(
                """
                SELECT f.arena_id, a.name
                FROM arena_follows f
                JOIN arenas a ON a.id = f.arena_id
                WHERE f.telegram_id = :tg
                ORDER BY f.id
                """
            ),
            {"tg": int(telegram_id)},
        )
    ).all()
    if not rows:
        return FollowChatReply(text="Вы ни за каким катком не следите.")
    if len(rows) == 1:
        return await unfollow_arena(
            session, telegram_id=telegram_id, arena_id=int(rows[0][0]), via="command"
        )
    buttons = []
    for arena_id, name in rows:
        label = f"Не следить: {str(name or '').strip() or 'каток'}"
        if len(label) > 64:
            label = label[:63] + "…"
        buttons.append(FollowButton(text=label, callback_data=f"{CB_UNFOLLOW_PREFIX}{int(arena_id)}"))
    return FollowChatReply(
        text="Вы следите за несколькими катками. Нажмите, за каким остановить.",
        buttons=tuple(buttons),
    )


async def keep_following(
    session: AsyncSession,
    *,
    telegram_id: int,
    arena_id: int,
    webapp_base_url: str = "",
) -> FollowChatReply:
    """«Следить дальше» после сообщения об открытии — подписка не гаснет."""
    row = (
        await session.execute(
            text(
                """
                UPDATE arena_follows
                SET muted_at = NULL
                WHERE telegram_id = :tg AND arena_id = :arena
                RETURNING id
                """
            ),
            {"tg": int(telegram_id), "arena": int(arena_id)},
        )
    ).first()
    if row is None:
        await session.commit()
        return FollowChatReply(text="Вы уже не следите за этим катком.", found=False, arena_id=int(arena_id))
    await session.execute(
        text(
            """
            UPDATE arena_follow_notifications
            SET payload = jsonb_set(COALESCE(payload, '{}'::jsonb), '{keep}', 'true'::jsonb, true)
            WHERE follow_id = :fid AND kind = 'reopened'
            """
        ),
        {"fid": int(row[0])},
    )
    await session.commit()
    arena = await _visible_arena(session, int(arena_id))
    name = str(arena["name"]).strip() if arena and arena["name"] else await _arena_label(session, arena_id)
    url = None
    if arena is not None:
        url = https_place_page_url(
            base_url=webapp_base_url,
            city_name=str(arena["city_name"] or ""),
            slug=str(arena["slug"]) if arena["slug"] else None,
        )
    buttons: tuple[FollowButton, ...] = ()
    if url:
        buttons = (FollowButton(text=BTN_SCHEDULE, web_app_url=url),)
    return FollowChatReply(
        text=f"Продолжаем следить за {html.escape(name)}. Напишем, если сеансы поменяются.",
        buttons=buttons,
        arena_id=int(arena_id),
        arena_name=name,
    )
