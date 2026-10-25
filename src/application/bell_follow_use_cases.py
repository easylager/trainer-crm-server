"""Колокольчик сайта: вход в мини-апп по ``follow_arena_<id>`` (подписка + разрешение писать).

Кнопка на сайте обещает «Напишем в Telegram, когда появится расписание». Для этого нужны
две вещи: подписка на каток и право бота писать первым. Подписку оформляет эта функция
в момент открытия мини-аппа, право спрашивает клиент (``Telegram.WebApp.requestWriteAccess``)
и сообщает исход сюда же, чтобы охват уведомлений можно было посчитать.

Вид подписки — ``sessions`` («сообщи о новых сеансах катка»): его же ставит кнопка на
пустой карточке и бот по ``/start watch_<id>``, и его одного шлёт проход доставки
напоминаний (``deliver_ice_watch_reminders``). ``season_open`` ждёт начала сезона по
календарю, а не появления расписания; ``schedule_fresh`` кнопки не имеет и доставляется
по тем же правилам, что ``sessions``.

События пишутся в ``platform_audit_events`` (свободный ``event_type``, миграция не нужна)
и скрыты из ленты админки.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_public_use_cases import get_public_arena_card
from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.client_session_use_cases import get_or_create_session
from src.application.client_ice_watch_use_cases import enrich_watch_row, subscribe_ice_watch
from src.application.client_use_cases import get_or_create_client
from src.application.ice_watch_bot_start import WATCH_START_FILTER
from src.application.platform_audit_use_cases import insert_platform_audit_from_record
from src.infrastructure.db.models import ICE_WATCH_KIND_SESSIONS
from src.infrastructure.repositories.client_ice_watch_repository import ClientIceWatchRepository

EVENT_SUBSCRIBED = "bell_follow_subscribed"
EVENT_GRANTED = "write_access_granted"
EVENT_DENIED = "write_access_denied"
EVENT_ALREADY = "write_access_already"
EVENT_UNSUPPORTED = "write_access_unsupported"

#: Исход запроса разрешения → тип события.
OUTCOME_EVENTS: dict[str, str] = {
    "granted": EVENT_GRANTED,
    "denied": EVENT_DENIED,
    "already": EVENT_ALREADY,
    "unsupported": EVENT_UNSUPPORTED,
}


async def _record(
    session: AsyncSession,
    event_type: str,
    *,
    telegram_id: int,
    client_id: int | None,
    arena_id: int | None,
    extra: dict[str, Any] | None = None,
    surface: str = "site_bell",
) -> None:
    payload: dict[str, Any] = {"surface": surface}
    if arena_id is not None:
        payload["arena_id"] = int(arena_id)
    if client_id is not None:
        payload["client_id"] = int(client_id)
    payload.update(extra or {})
    await insert_platform_audit_from_record(
        session,
        {
            "event": event_type,
            "actor_type": "client_bot",
            "actor_id": telegram_actor_hash(telegram_id) or "tg",
            "payload": payload,
        },
    )


async def follow_arena_from_bell(
    session: AsyncSession,
    *,
    telegram_id: int,
    arena_id: int,
    telegram_username: str | None = None,
) -> dict[str, Any] | None:
    """Гарантирует активную ``sessions``-подписку; ``None`` — катка нет в каталоге.

    Идемпотентно: у уже активной подписки ничего не трогаем (upsert сбросил бы
    ``last_notified_at``), повторное открытие даёт ``created=False`` и ту же строку.
    """
    card = await get_public_arena_card(session, str(int(arena_id)))
    if card is None:
        return None
    client_id = await get_or_create_client(session, telegram_id, telegram_username=telegram_username)
    await session.commit()
    # client_ice_watches.telegram_id ссылается на client_sessions (как в боте по /start watch_<id>).
    await get_or_create_session(telegram_id, session)
    aid = int(card["id"])
    repo = ClientIceWatchRepository(session)
    active = [
        w
        for w in await repo.list_active_for_client(int(client_id))
        if int(w["arena_id"]) == aid and w["watch_kind"] == ICE_WATCH_KIND_SESSIONS
    ]
    created = not active
    if created:
        watch = await subscribe_ice_watch(
            session,
            client_id=int(client_id),
            telegram_id=int(telegram_id),
            arena_id=aid,
            watch_kind=ICE_WATCH_KIND_SESSIONS,
            filter_json=dict(WATCH_START_FILTER),
            city_id=card.get("city_id"),
        )
    else:
        watch = await enrich_watch_row(session, active[0])
    await _record(
        session,
        EVENT_SUBSCRIBED,
        telegram_id=telegram_id,
        client_id=int(client_id),
        arena_id=aid,
        extra={"created": created},
    )
    await session.commit()
    return {
        "watch": watch,
        "created": created,
        "arena_id": aid,
        "arena_name": str(card.get("name") or ""),
    }


async def record_write_access_outcome(
    session: AsyncSession,
    *,
    telegram_id: int,
    client_id: int | None,
    arena_id: int,
    outcome: str,
    retry: bool = False,
) -> bool:
    """Пишет исход запроса разрешения; неизвестный исход -> ``False``, ничего не пишем."""
    event_type = OUTCOME_EVENTS.get(outcome)
    if event_type is None:
        return False
    await _record(
        session,
        event_type,
        telegram_id=telegram_id,
        client_id=client_id,
        arena_id=arena_id,
        extra={"retry": bool(retry)},
    )
    await session.commit()
    return True


#: Где в Mini App человек увидел запрос разрешения (поле ``surface`` в payload события).
WRITE_ACCESS_SURFACES = frozenset({"booking", "slot_wait", "arena_watch"})


async def record_surface_write_access_outcome(
    session: AsyncSession,
    *,
    telegram_id: int,
    client_id: int | None,
    surface: str,
    outcome: str,
    arena_id: int | None = None,
    trainer_id: int | None = None,
    retry: bool = False,
) -> bool:
    """Исход запроса разрешения с экрана записи, ожидания слотов или подписки на каток.

    Те же типы событий, что у колокольчика; различие только в ``surface``. Неизвестный
    исход или экран -> ``False``, ничего не пишем. В payload только хэш актора и id объектов.
    """
    event_type = OUTCOME_EVENTS.get(outcome)
    if event_type is None or surface not in WRITE_ACCESS_SURFACES:
        return False
    extra: dict[str, Any] = {"retry": bool(retry)}
    if trainer_id is not None:
        extra["trainer_id"] = int(trainer_id)
    await _record(
        session,
        event_type,
        telegram_id=telegram_id,
        client_id=client_id,
        arena_id=arena_id,
        extra=extra,
        surface=surface,
    )
    await session.commit()
    return True
