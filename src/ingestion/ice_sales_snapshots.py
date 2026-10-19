"""Persist Korona ticket sales counters for calibration (TASK-295)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, time, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.koronaticket_rink import KoronaRinkSession

logger = logging.getLogger(__name__)

_SOURCE_KORONA = "korona"

_LATEST_ROW = text("""
    SELECT capacity, sold, held
    FROM ice_sales_snapshots
    WHERE arena_id = :arena_id
      AND local_date = :local_date
      AND starts_at_local = :starts_at_local
    ORDER BY observed_at DESC
    LIMIT 1
    """)

_INSERT = text("""
    INSERT INTO ice_sales_snapshots (
        arena_id, local_date, starts_at_local, observed_at,
        capacity, sold, held, source
    )
    VALUES (
        :arena_id, :local_date, :starts_at_local, :observed_at,
        :capacity, :sold, :held, :source
    )
    """)


def _session_end_utc(
    session: KoronaRinkSession,
    *,
    timezone_name: str,
) -> datetime:
    tz = ZoneInfo(timezone_name)
    end_parts = session.ends_at_local.split(":")
    end_local = datetime.combine(
        session.local_date,
        time(int(end_parts[0]), int(end_parts[1])),
        tzinfo=tz,
    )
    return end_local.astimezone(timezone.utc)


def _is_past_session(
    session: KoronaRinkSession,
    *,
    observed_at: datetime,
    timezone_name: str,
) -> bool:
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return observed_at >= _session_end_utc(session, timezone_name=timezone_name)


async def record_korona_sales_if_changed(
    session: AsyncSession,
    *,
    arena_id: int,
    korona_sessions: Sequence[KoronaRinkSession],
    observed_at: datetime,
    timezone_name: str = "Europe/Minsk",
) -> int:
    """Insert rows only when counters differ from the latest snapshot for that session."""
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    inserted = 0
    for korona in korona_sessions:
        if _is_past_session(korona, observed_at=observed_at, timezone_name=timezone_name):
            continue
        start_parts = korona.starts_at_local.split(":")
        starts_at_local = time(int(start_parts[0]), int(start_parts[1]))
        latest = (
            await session.execute(
                _LATEST_ROW,
                {
                    "arena_id": arena_id,
                    "local_date": korona.local_date,
                    "starts_at_local": starts_at_local,
                },
            )
        ).one_or_none()
        capacity = korona.capacity
        sold = korona.sold
        held = korona.held
        if latest is not None and (latest.capacity == capacity and latest.sold == sold and latest.held == held):
            continue
        await session.execute(
            _INSERT,
            {
                "arena_id": arena_id,
                "local_date": korona.local_date,
                "starts_at_local": starts_at_local,
                "observed_at": observed_at,
                "capacity": capacity,
                "sold": sold,
                "held": held,
                "source": _SOURCE_KORONA,
            },
        )
        inserted += 1
    return inserted


class KoronaSalesSnapshotStore(Protocol):
    async def record_korona_sales(
        self,
        arena_id: int,
        korona_sessions: Sequence[KoronaRinkSession],
        *,
        observed_at: datetime,
        timezone_name: str,
    ) -> int: ...


class SqlAlchemyKoronaSalesSnapshotStore:
    def __init__(self, db_session: AsyncSession) -> None:
        self._session = db_session

    async def record_korona_sales(
        self,
        arena_id: int,
        korona_sessions: Sequence[KoronaRinkSession],
        *,
        observed_at: datetime,
        timezone_name: str,
    ) -> int:
        # Своя точка сохранения: ошибка БД откатывает только снимки, а не транзакцию прогона
        # (иначе Postgres отвергнет всё, что прогон пишет дальше в той же сессии).
        async with self._session.begin_nested():
            return await record_korona_sales_if_changed(
                self._session,
                arena_id=arena_id,
                korona_sessions=korona_sessions,
                observed_at=observed_at,
                timezone_name=timezone_name,
            )


async def try_record_korona_sales(
    store: KoronaSalesSnapshotStore | None,
    *,
    arena_id: int,
    korona_sessions: Sequence[KoronaRinkSession],
    observed_at: datetime,
    timezone_name: str,
) -> None:
    if store is None or not korona_sessions:
        return
    try:
        await store.record_korona_sales(
            arena_id,
            korona_sessions,
            observed_at=observed_at,
            timezone_name=timezone_name,
        )
    except Exception:
        logger.warning(
            "korona sales snapshot write failed arena_id=%s",
            arena_id,
            exc_info=True,
        )
