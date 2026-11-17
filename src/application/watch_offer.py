"""Предложение подписки на каток после содержательного просмотра (TASK-428, слой A).

Карточка катка (``/p/…`` на сайте и карточка арены в Mini App) один раз на человека и каток спокойно спрашивает
«Сообщить, когда на этом катке появятся новые сеансы?». Сайт ведёт в бота (``/start watch_<id>_o``), Mini App
подписывает сразу (``POST /client/ice-watches`` с ``origin=offer``).

Один раз — двумя защитами: ``localStorage`` в браузере и событие ``watch_offer_shown`` по ``actor_hash`` на сервере
(по нему же решаем, показывать ли снова). Подписанным не показываем. Без секрета актёра хэша нет — сервер видит
только подписку, повтор держит ``localStorage``. Любая ошибка сервера — не показывать.

События воронки — в ``catalog_consumer_events``: показ, нажатие, «Закрыть», подписка. Ключ дедупа без дня:
одно событие каждого вида на актёра и каток за всё время.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    KIND_WATCH_OFFER_CLICK,
    KIND_WATCH_OFFER_CLOSED,
    KIND_WATCH_OFFER_SHOWN,
    KIND_WATCH_OFFER_SUBSCRIBED,
    record_catalog_consumer_event,
    telegram_actor_hash,
)

logger = logging.getLogger(__name__)

ACTIONS = {
    "shown": KIND_WATCH_OFFER_SHOWN,
    "click": KIND_WATCH_OFFER_CLICK,
    "closed": KIND_WATCH_OFFER_CLOSED,
}
SURFACE_SITE = "place_page"
SURFACE_MINIAPP = "miniapp_arena"
SURFACE_NUDGE = "warm_nudge"  # подписка кнопкой из единственного напоминания (слой C)
ORIGIN_OFFER = "offer"
ORIGIN_NUDGE = "nudge"


def offer_dedup_key(kind: str, actor_hash: str | None, arena_id: int) -> str | None:
    if not actor_hash:
        return None
    return hashlib.sha256(f"{kind}|offer|{actor_hash}|{int(arena_id)}".encode()).hexdigest()


_ARENA = text("SELECT city_id FROM arenas WHERE id = :id AND is_active")
_SEEN = text("""
    SELECT 1 FROM catalog_consumer_events
    WHERE actor_hash = :actor AND arena_id = :arena AND kind = ANY(:kinds) LIMIT 1
    """)
_SUBSCRIBED = text("SELECT 1 FROM client_ice_watches WHERE telegram_id = :k AND arena_id = :arena AND active LIMIT 1")


async def _arena_city(session: AsyncSession, arena_id: int) -> tuple[bool, int | None]:
    row = (await session.execute(_ARENA, {"id": int(arena_id)})).first()
    if row is None:
        return False, None
    return True, (int(row[0]) if row[0] is not None else None)


async def offer_seen(session: AsyncSession, *, actor_hash: str | None, arena_id: int) -> bool:
    """Предложение этому актёру на этом катке уже показывали (или он его закрыл)."""
    if not actor_hash:
        return False
    kinds = [KIND_WATCH_OFFER_SHOWN, KIND_WATCH_OFFER_CLOSED, KIND_WATCH_OFFER_SUBSCRIBED]
    row = await session.execute(_SEEN, {"actor": actor_hash, "arena": int(arena_id), "kinds": kinds})
    return row.first() is not None


async def offer_state(
    session: AsyncSession, *, arena_id: int, actor_hash: str | None, telegram_id: int | None = None
) -> dict[str, Any]:
    """``{"show": bool}`` — можно ли показать предложение. Сомнение (ошибка, нет катка) — не показывать."""
    try:
        if int(arena_id) <= 0:
            return {"show": False}
        exists, _ = await _arena_city(session, arena_id)
        if not exists:
            return {"show": False}
        if telegram_id is not None and int(telegram_id) > 0:
            if (await session.execute(_SUBSCRIBED, {"k": int(telegram_id), "arena": int(arena_id)})).first():
                return {"show": False, "subscribed": True}
        if await offer_seen(session, actor_hash=actor_hash, arena_id=arena_id):
            return {"show": False}
        return {"show": True}
    except Exception:  # noqa: BLE001 — закрыто по умолчанию
        logger.warning("watch offer state failed arena=%s", arena_id, exc_info=True)
        await session.rollback()
        return {"show": False}


async def record_offer_event(
    session: AsyncSession,
    *,
    kind: str,
    surface: str,
    arena_id: int,
    actor_hash: str | None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Записать событие воронки. Неизвестный каток — ничего (FK уронил бы вставку)."""
    exists, city_id = await _arena_city(session, arena_id)
    if not exists:
        return False
    return await record_catalog_consumer_event(
        session,
        kind=kind,
        surface=surface,
        actor_hash=actor_hash,
        city_id=city_id,
        arena_id=int(arena_id),
        payload=dict(payload or {}),
        dedup_key=offer_dedup_key(kind, actor_hash, arena_id),
    )


async def record_subscribed_from(
    session: AsyncSession, *, telegram_id: int, arena_id: int, origin: str | None, surface: str
) -> None:
    """Подписка пришла из предложения (сайт через бота, Mini App) или из напоминания: событие для воронки.
    Прочие подписки (колокольчик, пустая карточка) сюда не пишутся. Сбой учёта подписку не отменяет."""
    if origin not in (ORIGIN_OFFER, ORIGIN_NUDGE):
        return
    try:
        await record_offer_event(
            session,
            kind=KIND_WATCH_OFFER_SUBSCRIBED,
            surface=surface,
            arena_id=arena_id,
            actor_hash=telegram_actor_hash(telegram_id),
            payload={"origin": origin},
        )
    except Exception:  # noqa: BLE001
        logger.warning("watch offer subscribed event failed", exc_info=True)


__all__ = [
    "ACTIONS",
    "ORIGIN_NUDGE",
    "ORIGIN_OFFER",
    "SURFACE_MINIAPP",
    "SURFACE_NUDGE",
    "SURFACE_SITE",
    "offer_dedup_key",
    "offer_seen",
    "offer_state",
    "record_offer_event",
    "record_subscribed_from",
]
