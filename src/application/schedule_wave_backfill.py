"""Восстановление волн расписания по журналу прогонов ``ice_scrape_runs`` (TASK-329, AC3).

Дат слотов в журнале нет — только ``slots_found``. Детектор из исследования TASK-327 (блок A):

* ряд ``slots_found`` по каждому заданию парсера (``job_id``), только прогоны ``ok``/``empty``;
* событие — рост к предыдущему ok/empty-прогону того же задания: ``0 → N`` или прирост
  ≥2 слотов и ≥30%;
* события одного катка в пределах 6 ч от предыдущей учтённой волны сливаются в одну.

Ряд строится по заданию, а не по катку: у катка бывает несколько заданий (например,
ОХМ отдельно), и их чередование в общем ряду давало бы ложные скачки.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schedule_promise import MERGE_WITHIN

COUNTED_STATUSES = frozenset({"ok", "empty"})
MIN_ABS_GROWTH = 2
# ≥30% как дробь: (cur − prev) * 10 ≥ prev * 3.
MIN_REL_GROWTH_NUM = 3
MIN_REL_GROWTH_DEN = 10
# Сколько дней журнала до ``since`` берём, чтобы у первого прогона окна был предыдущий.
CONTEXT_DAYS = 7


@dataclass(frozen=True)
class RunPoint:
    run_id: int
    job_id: int
    arena_id: int
    finished_at: datetime
    status: str
    slots_found: int


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def is_growth(previous: int, current: int) -> bool:
    if previous <= 0:
        return current > 0
    delta = current - previous
    return delta >= MIN_ABS_GROWTH and delta * MIN_REL_GROWTH_DEN >= previous * MIN_REL_GROWTH_NUM


def detect_backfill_waves(
    runs: Iterable[RunPoint],
    *,
    since: datetime,
    until: datetime | None = None,
    until_by_arena: Mapping[int, datetime] | None = None,
) -> dict[int, list[datetime]]:
    """Волны по каткам: ``{arena_id: [detected_at, ...]}`` в ``[since, until)``.

    ``until_by_arena`` — граница для катка (первая живая запись ``seed``/``parser``/``admin``):
    дальше волны пишутся вживую, восстановление их не дублирует.
    """
    since = _aware(since)
    until = _aware(until) if until is not None else None
    per_job: dict[int, list[RunPoint]] = defaultdict(list)
    for run in runs:
        if run.status in COUNTED_STATUSES:
            per_job[run.job_id].append(run)

    events: dict[int, list[datetime]] = defaultdict(list)
    for series in per_job.values():
        series.sort(key=lambda r: (_aware(r.finished_at), r.run_id))
        for previous, current in zip(series, series[1:]):
            if not is_growth(int(previous.slots_found), int(current.slots_found)):
                continue
            moment = _aware(current.finished_at)
            if moment < since:
                continue
            bound = (until_by_arena or {}).get(current.arena_id, until)
            if bound is not None and moment >= _aware(bound):
                continue
            events[current.arena_id].append(moment)

    merged: dict[int, list[datetime]] = {}
    for arena_id, moments in events.items():
        kept: list[datetime] = []
        for moment in sorted(moments):
            if kept and moment - kept[-1] < MERGE_WITHIN:
                continue
            kept.append(moment)
        merged[arena_id] = kept
    return merged


async def load_run_points(session: AsyncSession, *, since: datetime, until: datetime) -> list[RunPoint]:
    result = await session.execute(
        text(
            """
            SELECT id, job_id, arena_id, finished_at, status, slots_found
            FROM ice_scrape_runs
            WHERE finished_at >= :from_ts
              AND finished_at < :until
              AND status IN ('ok', 'empty')
            ORDER BY job_id, finished_at, id
            """
        ),
        {"from_ts": _aware(since) - timedelta(days=CONTEXT_DAYS), "until": _aware(until)},
    )
    return [
        RunPoint(
            run_id=int(row[0]),
            job_id=int(row[1]),
            arena_id=int(row[2]),
            finished_at=row[3],
            status=str(row[4]),
            slots_found=int(row[5] or 0),
        )
        for row in result.fetchall()
    ]


async def load_live_start_by_arena(session: AsyncSession) -> dict[int, datetime]:
    """Первая живая запись (seed/parser/admin) катка — с неё волны пишутся вживую."""
    result = await session.execute(
        text(
            """
            SELECT arena_id, min(detected_at)
            FROM ice_schedule_waves
            WHERE source <> 'backfill'
            GROUP BY arena_id
            """
        )
    )
    return {int(row[0]): row[1] for row in result.fetchall()}


async def replace_backfill_waves(
    session: AsyncSession, waves: Mapping[int, list[datetime]], *, since: datetime
) -> int:
    """Идемпотентно: все прежние backfill-строки окна удаляются, найденные пишутся заново."""
    arena_ids = sorted(waves)
    await session.execute(
        text("DELETE FROM ice_schedule_waves WHERE source = 'backfill' AND detected_at >= :since"),
        {"since": _aware(since)},
    )
    inserted = 0
    for arena_id in arena_ids:
        for moment in waves[arena_id]:
            await session.execute(
                text(
                    """
                    INSERT INTO ice_schedule_waves
                        (arena_id, detected_at, horizon_before, horizon_after, source)
                    VALUES (:arena_id, :detected_at, NULL, NULL, 'backfill')
                    """
                ),
                {"arena_id": arena_id, "detected_at": moment},
            )
            inserted += 1
    return inserted
