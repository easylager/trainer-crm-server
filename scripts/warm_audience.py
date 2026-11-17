#!/usr/bin/env python3
"""Кому уйдут сообщения прогрева посетителей (TASK-428) — перед шагом «белый список → все». Только читает базу.

Прогоняет поводы прогрева на момент ``--at`` (по умолчанию сейчас; утренние поводы — только с 9:00 до 11:00 по Минску,
неделя — по четвергам) и печатает, сколько людей получило бы каждый повод, а с ``--ids`` — их telegram_id (имена
не печатаются никогда). Допуск здесь не вызывается: бюджет, тихие часы, «Не присылать» и флаги срежут часть
списка при настоящем проходе — это видно в журнале сухого прогона (вторая часть вывода, за ``--days`` суток).

Транзакция только для чтения (``SET TRANSACTION READ ONLY``): скрипт ничего не пишет и никому не отправляет.
Запуск в проде: ``railway run -s <сервис> -- python scripts/warm_audience.py --at 2026-11-20T09:30``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MINSK = ZoneInfo("Europe/Minsk")


def parse_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    value = datetime.fromisoformat(raw)
    return value if value.tzinfo else value.replace(tzinfo=MINSK)


async def audience(session, *, now: datetime) -> dict[str, list[int]]:
    from src.application.warm_notify import PRODUCERS

    out: dict[str, list[int]] = {}
    for kind, producer in PRODUCERS.items():
        proposals = await producer(session, now=now)
        out[kind] = sorted({int(p.notice.player_key) for p in proposals})
    return out


async def dry_run_journal(session, *, since: datetime) -> Counter:
    from sqlalchemy import text

    rows = await session.execute(
        text("""
            SELECT kind, decision, COALESCE(reason, '') FROM kk_notify_decisions
            WHERE kind LIKE 'warm\\_%' AND tick_at >= :since
            """),
        {"since": since},
    )
    return Counter((str(k), str(d), str(r)) for k, d, r in rows.all())


def render(people: dict[str, list[int]], journal: Counter, *, now: datetime, ids: bool, days: int) -> str:
    lines = [f"Поводы на {now.astimezone(MINSK):%d.%m.%Y %H:%M} по Минску (без допуска):"]
    for kind, keys in people.items():
        lines.append(f"  {kind}: {len(keys)}" + (f" — {', '.join(map(str, keys))}" if ids and keys else ""))
    lines.append(f"Журнал решений прогрева за {days} сут. (повод · решение · причина: записей):")
    if not journal:
        lines.append("  пусто")
    for (kind, decision, reason), n in sorted(journal.items()):
        lines.append(f"  {kind} · {decision} · {reason or '—'}: {n}")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> str:
    from sqlalchemy import text

    from src.infrastructure.db.session import async_session_factory

    now = parse_at(args.at)
    async with async_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        people = await audience(session, now=now)
        journal = await dry_run_journal(session, since=now - timedelta(days=args.days))
        await session.rollback()
    return render(people, journal, now=now, ids=args.ids, days=args.days)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Кому уйдут сообщения прогрева (только чтение).")
    p.add_argument("--at", default=None, help="момент прохода, ISO; без зоны — по Минску")
    p.add_argument("--ids", action="store_true", help="печатать telegram_id (имена не печатаются)")
    p.add_argument("--days", type=int, default=7, help="за сколько суток показать журнал сухого прогона")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)
    print(asyncio.run(run(args)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
