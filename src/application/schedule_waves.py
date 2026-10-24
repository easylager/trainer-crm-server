"""Волны публикации расписания катка: запись и поля карточки (TASK-329).

* **Горизонт** катка — максимальная ``local_date`` будущих (``starts_at_utc > now``)
  сеансов ``public_skate``/``open_ice`` со статусом ``active``.
* **Волна** — горизонт вырос по сравнению с последней записью катка
  (``parser``/``admin``/``seed``; восстановленные ``backfill`` без горизонтов
  точкой сравнения не служат).
* Первая запись катка — ``seed``: точка отсчёта, в статистику не входит, чтобы
  деплой не родил «волну» у всех катков разом.

Сжатие горизонта не пишется: иначе источник, мигнувший урезанной выдачей, давал бы
ложную волну при возврате к прежнему горизонту.

Запись вызывается строго после коммита публикации (планировщик — после
``checkpoint``) и после коммита админского сохранения. Её сбой только логируется:
публикация и сохранение уже закоммичены и не откатываются.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schedule_habit import (
    ScheduleWave,
    no_habit,
    resolve_zone,
    schedule_habit,
    waves_in_window,
    window_start,
)

logger = logging.getLogger(__name__)

SOURCE_PARSER = "parser"
SOURCE_ADMIN = "admin"
SOURCE_SEED = "seed"
SOURCE_BACKFILL = "backfill"

RESULT_SEED = "seed"
RESULT_WAVE = "wave"

# Ключ advisory-лока: планировщик и админка могут писать волну одного катка
# одновременно — без лока оба увидят старый горизонт и запишут волну дважды.
_LOCK_NAMESPACE = "ice_schedule_waves"


async def arena_schedule_horizon(session: AsyncSession, arena_id: int, *, now: datetime) -> date | None:
    result = await session.execute(
        text(
            """
            SELECT max(local_date)
            FROM ice_sessions
            WHERE arena_id = :arena_id
              AND kind IN ('public_skate', 'open_ice')
              AND status = 'active'
              AND starts_at_utc > :now
            """
        ),
        {"arena_id": int(arena_id), "now": now},
    )
    return result.scalar()


async def record_schedule_wave(
    session: AsyncSession,
    arena_id: int,
    *,
    source: str,
    now: datetime | None = None,
) -> str | None:
    """Пересчитать горизонт и, если надо, записать строку. Коммит — за вызывающим.

    Возвращает ``"seed"``, ``"wave"`` или ``None`` (горизонт не вырос).
    """
    if source not in (SOURCE_PARSER, SOURCE_ADMIN):
        raise ValueError(f"unsupported live wave source: {source!r}")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:ns), :arena_id)"),
        {"ns": _LOCK_NAMESPACE, "arena_id": int(arena_id)},
    )
    horizon = await arena_schedule_horizon(session, arena_id, now=now)
    last = (
        await session.execute(
            text(
                """
                SELECT horizon_after
                FROM ice_schedule_waves
                WHERE arena_id = :arena_id
                  AND source <> 'backfill'
                ORDER BY detected_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"arena_id": int(arena_id)},
        )
    ).first()
    if last is None:
        await _insert_wave(session, arena_id, now=now, before=None, after=horizon, source=SOURCE_SEED)
        return RESULT_SEED
    baseline = last[0]
    if horizon is None or (baseline is not None and horizon <= baseline):
        return None
    await _insert_wave(session, arena_id, now=now, before=baseline, after=horizon, source=source)
    return RESULT_WAVE


async def _insert_wave(
    session: AsyncSession,
    arena_id: int,
    *,
    now: datetime,
    before: date | None,
    after: date | None,
    source: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO ice_schedule_waves (arena_id, detected_at, horizon_before, horizon_after, source)
            VALUES (:arena_id, :detected_at, :before, :after, :source)
            """
        ),
        {
            "arena_id": int(arena_id),
            "detected_at": now,
            "before": before,
            "after": after,
            "source": source,
        },
    )


async def record_parser_wave_in_own_session(
    arena_id: int,
    *,
    session_factory: Callable[[], Any] | None = None,
) -> str | None:
    """После коммита публикации парсера: своя сессия, свой коммит, любой сбой — в лог."""
    try:
        factory = session_factory
        if factory is None:
            from src.infrastructure.db.session import async_session_factory

            factory = async_session_factory
        async with factory() as session:
            outcome = await record_schedule_wave(session, arena_id, source=SOURCE_PARSER)
            await session.commit()
            return outcome
    except Exception:  # noqa: BLE001 — публикация уже закоммичена, волна — не повод её ронять
        logger.exception("schedule wave record failed arena_id=%s source=parser", arena_id)
        return None


def parser_wave_recorder(
    session_factory: Callable[[], Any] | None = None,
) -> Callable[[int], Awaitable[str | None]]:
    """Колбэк для ``IceIngestScheduler(schedule_wave_recorder=...)``."""

    async def _record(arena_id: int) -> str | None:
        return await record_parser_wave_in_own_session(arena_id, session_factory=session_factory)

    return _record


async def record_admin_wave_after_commit(session: AsyncSession, arena_id: int | None) -> str | None:
    """После коммита админского сохранения, в той же сессии. Сбой — в лог, ответ не меняется."""
    if arena_id is None:
        return None
    try:
        outcome = await record_schedule_wave(session, int(arena_id), source=SOURCE_ADMIN)
        await session.commit()
        return outcome
    except Exception:  # noqa: BLE001 — сеансы уже сохранены
        logger.exception("schedule wave record failed arena_id=%s source=admin", arena_id)
        await _rollback_quietly(session)
        return None


async def record_admin_wave_for_recurrence_after_commit(
    session: AsyncSession, recurrence_key: str
) -> str | None:
    """То же после rematerialize: арену серии ищем по ключу. Сбой — в лог."""
    try:
        arena_id = await arena_id_for_recurrence(session, recurrence_key)
    except Exception:  # noqa: BLE001 — сеансы уже сохранены
        logger.exception("schedule wave: arena lookup failed recurrence_key=%s", recurrence_key)
        await _rollback_quietly(session)
        return None
    return await record_admin_wave_after_commit(session, arena_id)


async def _rollback_quietly(session: AsyncSession) -> None:
    try:
        await session.rollback()
    except Exception:  # noqa: BLE001
        logger.exception("rollback after schedule wave failure failed")


async def arena_id_for_recurrence(session: AsyncSession, recurrence_key: str) -> int | None:
    value = (
        await session.execute(
            text("SELECT arena_id FROM ice_sessions WHERE recurrence_key = :key LIMIT 1"),
            {"key": recurrence_key},
        )
    ).scalar()
    return int(value) if value is not None else None


async def load_card_inputs(
    session: AsyncSession, arena_id: int, *, since: datetime, now: datetime
) -> tuple[list[ScheduleWave], date | None]:
    """Волны окна (без seed) и горизонт одним запросом: страница места считает SQL (TASK-197)."""
    row = (
        await session.execute(
            text(
                """
                SELECT
                    (
                        SELECT max(local_date)
                        FROM ice_sessions
                        WHERE arena_id = :arena_id
                          AND kind IN ('public_skate', 'open_ice')
                          AND status = 'active'
                          AND starts_at_utc > :now
                    ) AS horizon,
                    (
                        SELECT array_agg(detected_at ORDER BY detected_at, id)
                        FROM ice_schedule_waves
                        WHERE arena_id = :arena_id
                          AND detected_at >= :since
                          AND detected_at <= :now
                          AND source <> 'seed'
                    ) AS waves
                """
            ),
            {"arena_id": int(arena_id), "now": now, "since": since},
        )
    ).one()
    # source внутри окна функции уже не важен: seed отфильтрован в SQL.
    waves = [ScheduleWave(detected_at=moment, source=SOURCE_PARSER) for moment in (row[1] or [])]
    return waves, row[0]


def empty_card_fields() -> dict[str, Any]:
    return {"schedule_habit": no_habit(), "schedule_horizon": None}


async def schedule_card_fields(
    session: AsyncSession,
    arena_id: int,
    *,
    tz_name: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """``schedule_habit`` + ``schedule_horizon`` для карточки катка (Mini App и сайт).

    Окно 42 дня считается от ``now`` здесь. Горизонт — ISO-строка: карточка уходит и
    в JSON API, и в ``json_for_script`` сайта. Сбой (например, таблицы ещё нет) не роняет
    карточку: savepoint откатывает только этот запрос, поля — «привычки нет».
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        async with session.begin_nested():
            waves, horizon = await load_card_inputs(session, arena_id, since=window_start(now), now=now)
    except Exception:  # noqa: BLE001 — карточка важнее наблюдения
        logger.exception("schedule card fields failed arena_id=%s", arena_id)
        return empty_card_fields()
    return {
        "schedule_habit": schedule_habit(
            waves_in_window(waves, now=now), resolve_zone(tz_name), now=now
        ),
        "schedule_horizon": horizon.isoformat() if horizon is not None else None,
    }
