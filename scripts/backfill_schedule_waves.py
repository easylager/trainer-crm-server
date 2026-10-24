"""TASK-329: восстановить волны публикации расписания из ice_scrape_runs.

Детектор (исследование TASK-327, блок A): по каждому заданию парсера ряд ``slots_found``
ok/empty-прогонов; волна — ``0 → N`` или прирост ≥2 и ≥30% к предыдущему прогону;
события катка в пределах 6 ч сливаются. Пишется ``source='backfill'``, горизонты NULL.
У катка, где волны уже пишутся вживую (есть seed/parser/admin), восстановление
обрывается на первой живой записи — без дублей.

По умолчанию — dry-run в READ ONLY транзакции: печатает волны по каткам и привычку,
которую карточка показала бы сейчас. ``--apply`` пишет (идемпотентно: прежние
backfill-строки окна заменяются). Облачная БД — только с ``--i-know-this-is-prod``;
``--apply`` на проде запускать только с согласия владельца.

Usage:
  PYTHONPATH=. python scripts/backfill_schedule_waves.py
  PYTHONPATH=. python scripts/backfill_schedule_waves.py --since 2026-10-06 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.schedule_habit import ScheduleWave, resolve_zone, schedule_habit, waves_in_window
from src.application.schedule_wave_backfill import (
    detect_backfill_waves,
    load_live_start_by_arena,
    load_run_points,
    replace_backfill_waves,
)
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)

DEFAULT_SINCE = date(2026, 10, 6)
_WEEKDAYS_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        raise SystemExit("Set DATABASE_URL_SYNC or DATABASE_URL")
    return normalize_db_url(raw)


async def _table_exists(session: AsyncSession) -> bool:
    return (await session.execute(text("SELECT to_regclass('ice_schedule_waves') IS NOT NULL"))).scalar()


async def _arenas(session: AsyncSession) -> dict[int, tuple[str, str | None]]:
    result = await session.execute(
        text(
            """
            SELECT a.id, a.name, p.timezone
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id IN (SELECT DISTINCT arena_id FROM ice_parser_jobs)
            """
        )
    )
    return {int(r[0]): (str(r[1]), r[2]) for r in result.fetchall()}


async def _live_waves(session: AsyncSession) -> dict[int, list[ScheduleWave]]:
    result = await session.execute(
        text(
            """
            SELECT arena_id, detected_at, source
            FROM ice_schedule_waves
            WHERE source IN ('parser', 'admin')
            """
        )
    )
    out: dict[int, list[ScheduleWave]] = {}
    for row in result.fetchall():
        out.setdefault(int(row[0]), []).append(ScheduleWave(detected_at=row[1], source=str(row[2])))
    return out


def _fmt(moment: datetime, tz_name: str | None) -> str:
    local = moment.astimezone(resolve_zone(tz_name))
    return f"{_WEEKDAYS_RU[local.weekday()]} {local:%d.%m %H:%M}"


async def run(
    session: AsyncSession,
    *,
    since: datetime,
    now: datetime,
    apply: bool,
    out=print,
) -> dict[str, int]:
    """Ядро скрипта (тестируется на фикстуре). Возвращает счётчики уровней привычки."""
    table = await _table_exists(session)
    if apply and not table:
        raise SystemExit("ice_schedule_waves is missing: run alembic upgrade head first")
    live_start = await load_live_start_by_arena(session) if table else {}
    live = await _live_waves(session) if table else {}
    runs = await load_run_points(session, since=since, until=now)
    waves = detect_backfill_waves(runs, since=since, until=now, until_by_arena=live_start)
    arenas = await _arenas(session)

    levels: Counter[str] = Counter()
    for arena_id in sorted(set(arenas) | set(waves)):
        name, tz_name = arenas.get(arena_id, (f"arena {arena_id}", None))
        moments = waves.get(arena_id, [])
        habit = schedule_habit(
            waves_in_window(
                [ScheduleWave(detected_at=m, source="backfill") for m in moments] + live.get(arena_id, []),
                now=now,
            ),
            tz_name,
        )
        levels[habit["level"]] += 1
        detail = f" weekday={_WEEKDAYS_RU[habit['weekday']]}" if habit["weekday"] is not None else ""
        when = ", ".join(_fmt(m, tz_name) for m in moments) or "—"
        out(f"{arena_id:>4} {name[:40]:<40} waves={len(moments)} habit={habit['level']}{detail} | {when}")

    out(
        f"total arenas={sum(levels.values())} day={levels['day']} week={levels['week']} "
        f"none={levels['none']} backfill_waves={sum(len(v) for v in waves.values())}"
    )
    if apply:
        inserted = await replace_backfill_waves(session, waves, since=since)
        await session.commit()
        out(f"applied: inserted {inserted} backfill rows")
    else:
        out("dry-run; pass --apply to write ice_schedule_waves")
    return dict(levels)


async def main_async(*, since_day: date, apply: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        warn_prod_ack()
    engine = create_async_engine(async_database_url(url))
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    since = datetime.combine(since_day, time(0, 0), tzinfo=resolve_zone("Europe/Minsk"))
    try:
        async with Session() as session:
            if not apply:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            await run(session, since=since, now=datetime.now(timezone.utc), apply=apply)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", type=date.fromisoformat, default=DEFAULT_SINCE)
    parser.add_argument("--apply", action="store_true", help="write rows (default: dry-run)")
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    asyncio.run(
        main_async(since_day=args.since, apply=args.apply, i_know_this_is_prod=args.i_know_this_is_prod)
    )


if __name__ == "__main__":
    main()
