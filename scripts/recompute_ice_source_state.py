"""Разовый пересчёт состояния источников льда по истории ice_scrape_runs (TASK-178).

До TASK-178 пустой прогон при пустой витрине обнулял серию сбоев, а устаревание
алертилось только при видимых сеансах. Поэтому ``failure_streak`` / ``failing_since`` /
``last_error_*`` в ``ice_parser_jobs`` посчитаны по старым правилам, и ``alert_state``
им соответствует. Скрипт проигрывает историю прогонов каждого задания через
``next_source_state`` (новые правила) и печатает таблицу «было → станет».

- По умолчанию dry-run, транзакция READ ONLY — ничего не пишет.
- ``--apply`` пишет пересчитанные колонки состояния (под локом планировщика).
  ``alert_state`` не трогает: следующий тик алертов (≤ 2 мин) сам пошлёт честные
  🔴 / ✅ по разнице — колонка «alert после тика» показывает, к чему он придёт.
- ``--apply --silent`` дополнительно выставляет ``alert_state`` без сообщений в админ-бот
  (для перехода в failing ``alert_sent_at = NULL`` — днём придёт напоминание 🟠).
- Облако/Railway — только с ``--i-know-this-is-prod`` (и для dry-run).

Историческое число видимых сеансов не хранится: для пустых прогонов берётся текущая
витрина (то же приближение, что в backfill миграции 0211).

Usage:
  PYTHONPATH=. python scripts/recompute_ice_source_state.py
  PYTHONPATH=. python scripts/recompute_ice_source_state.py --i-know-this-is-prod
  PYTHONPATH=. python scripts/recompute_ice_source_state.py --apply --i-know-this-is-prod
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.ingestion.freshness import replay_source_state
from src.ingestion.source_alerts import SourceHealthRow, is_alerting, load_source_health_rows
from src.ingestion.types import ALERT_STATE_FAILING, ALERT_STATE_OK, ScrapeRunRecord, SourceState
from src.shared.ops_db_guard import (
    add_i_know_this_is_prod_argument,
    assert_database_url,
    assert_railway_target_database,
    async_database_url,
    normalize_db_url,
    warn_prod_ack,
)

SUCCESS_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Plan:
    row: SourceHealthRow
    state: SourceState
    ok_7d: int
    runs_7d: int
    alert_after: str

    @property
    def changed(self) -> bool:
        r, s = self.row, self.state
        return (
            r.failure_streak != s.failure_streak
            or r.failing_since != s.failing_since
            or r.last_ok_at != s.last_ok_at
            or r.last_error_code != s.last_error_code
        )


def _db_url() -> str:
    raw = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC")
    if not raw:
        raise SystemExit("Set DATABASE_URL")
    return normalize_db_url(raw)


async def _runs(session: AsyncSession, job_id: int) -> list[ScrapeRunRecord]:
    result = await session.execute(
        text(
            """
            SELECT job_id, arena_id, status, slots_found, slots_dropped, error_code,
                   error_summary, started_at, finished_at, http_status
            FROM ice_scrape_runs WHERE job_id = :job_id ORDER BY finished_at, id
            """
        ),
        {"job_id": job_id},
    )
    return [
        ScrapeRunRecord(
            job_id=int(r.job_id),
            arena_id=int(r.arena_id),
            parser_key="",
            status=str(r.status),
            slot_count=int(r.slots_found or 0),
            slots_dropped=int(r.slots_dropped or 0),
            error_message=r.error_summary,
            started_at=r.started_at,
            finished_at=r.finished_at,
            http_status=r.http_status,
            error_code=r.error_code,
        )
        for r in result
    ]


async def build_plan(session: AsyncSession, *, now: datetime) -> list[Plan]:
    plans: list[Plan] = []
    for row in await load_source_health_rows(session, now=now):
        runs = await _runs(session, row.job_id)
        # last_ok_at из истории может быть уже вычищен TTL (90 дней) — тогда берём текущий.
        start = SourceState(last_ok_at=row.last_ok_at, last_ok_slot_count=row.last_ok_slot_count)
        state = replay_source_state(runs, shown_sessions=row.shown_sessions, start=start)
        recent = [r for r in runs if r.finished_at >= now - SUCCESS_WINDOW]
        planned_row = replace(
            row,
            last_ok_at=state.last_ok_at,
            last_ok_slot_count=state.last_ok_slot_count,
            failing_since=state.failing_since,
            failure_streak=state.failure_streak,
            last_error_code=state.last_error_code,
            last_error_summary=state.last_error_summary,
        )
        alert_after = ALERT_STATE_FAILING if is_alerting(planned_row, now) else ALERT_STATE_OK
        plans.append(
            Plan(
                row=row,
                state=state,
                ok_7d=sum(1 for r in recent if r.status == "ok"),
                runs_7d=len(recent),
                alert_after=alert_after,
            )
        )
    return plans


def _short(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).strftime("%m-%d %H:%M") if value else "—"


def print_plan(plans: list[Plan]) -> None:
    print(
        "| job | parser_key | ok/runs 7д | last_ok | streak | last_error_code | alert_state | alert после тика |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for p in plans:
        r, s = p.row, p.state
        streak = f"{r.failure_streak}" if r.failure_streak == s.failure_streak else f"{r.failure_streak}→{s.failure_streak}"
        code = (
            f"{r.last_error_code or '—'}"
            if r.last_error_code == s.last_error_code
            else f"{r.last_error_code or '—'}→{s.last_error_code or '—'}"
        )
        alert = r.alert_state if r.alert_state == p.alert_after else f"**{r.alert_state}→{p.alert_after}**"
        print(
            f"| {r.job_id} | {r.parser_key} | {p.ok_7d}/{p.runs_7d} | {_short(s.last_ok_at)} | "
            f"{streak} | {code} | {r.alert_state} | {alert} |"
        )
    flips = sum(1 for p in plans if p.row.alert_state != p.alert_after)
    print(f"\njobs={len(plans)} state_changed={sum(p.changed for p in plans)} alert_flips={flips}")


async def apply_plan(session: AsyncSession, plans: list[Plan], *, silent: bool) -> None:
    for p in plans:
        s = p.state
        await session.execute(
            text(
                """
                UPDATE ice_parser_jobs
                SET last_ok_at = :last_ok_at, last_ok_slot_count = :last_ok_slot_count,
                    failing_since = :failing_since, failure_streak = :failure_streak,
                    last_error_code = :code, last_error_summary = :summary
                WHERE id = :id
                """
            ),
            {
                "id": p.row.job_id,
                "last_ok_at": s.last_ok_at,
                "last_ok_slot_count": s.last_ok_slot_count,
                "failing_since": s.failing_since,
                "failure_streak": s.failure_streak,
                "code": (s.last_error_code or "")[:64] or None,
                "summary": s.last_error_summary,
            },
        )
        if silent and p.row.alert_state != p.alert_after:
            # В failing без 🔴: alert_sent_at = NULL, чтобы днём ушло напоминание 🟠.
            sent_at = None if p.alert_after == ALERT_STATE_FAILING else p.row.alert_sent_at
            await session.execute(
                text(
                    "UPDATE ice_parser_jobs SET alert_state = :state, alert_sent_at = :sent_at WHERE id = :id"
                ),
                {"id": p.row.job_id, "state": p.alert_after, "sent_at": sent_at},
            )


async def run(*, apply: bool, silent: bool, i_know_this_is_prod: bool) -> None:
    url = _db_url()
    assert_database_url(url, apply=apply, allow_prod=i_know_this_is_prod)
    if i_know_this_is_prod:
        assert_railway_target_database(url)
        warn_prod_ack()
    engine = create_async_engine(async_database_url(url))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    try:
        if not apply:
            async with factory() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))
                print_plan(await build_plan(session, now=now))
                await session.rollback()
            print("\ndry-run: nothing written (add --apply to write)")
            return

        from src.ingestion.scheduler_lock import run_with_ice_ingest_lock

        async def work() -> list[Plan]:
            async with factory() as session:
                plans = await build_plan(session, now=now)
                await apply_plan(session, plans, silent=silent)
                await session.commit()
                return plans

        acquired, plans = await run_with_ice_ingest_lock(engine, work)
        if not acquired or plans is None:
            raise SystemExit("ice ingest scheduler holds the lock; retry in a minute")
        print_plan(plans)
        print("\napplied" + (" (alert_state synced silently)" if silent else ""))
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write recomputed state (default: dry-run)")
    parser.add_argument(
        "--silent",
        action="store_true",
        help="with --apply: also set alert_state directly, without admin-bot messages",
    )
    add_i_know_this_is_prod_argument(parser)
    args = parser.parse_args()
    if args.silent and not args.apply:
        parser.error("--silent requires --apply")
    asyncio.run(run(apply=args.apply, silent=args.silent, i_know_this_is_prod=args.i_know_this_is_prod))


if __name__ == "__main__":
    main()
