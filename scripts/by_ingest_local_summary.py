"""Сводка после scripts/by_ingest_local.sh: будущие сеансы по аренам BY-источников и по видам.

Для СДЮШОР (ledlife_origin_html_v1) — ещё зал и цены (взрослый/детский/прокат и тарифы price_tiers).
Только чтение, только локальная база (хост проверяет обёртка, здесь — ещё раз).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BY_KEYS = (
    "ledlife_origin_html_v1",
    "gorki_lds_v1",
    "bobruisk_arena_v1",
    "soligorsk_szk_v1",
    "minskarena_speed_oval_v1",
)


def _money(v: int | None) -> str:
    return "—" if v is None else f"{v / 100:.2f}"


async def main() -> None:
    from sqlalchemy import text

    from src.infrastructure.db.session import async_session_factory

    host = (urlparse(os.environ.get("DATABASE_URL", "")).hostname or "").lower()
    if not (host in {"localhost", "::1"} or host.startswith("127.")):
        sys.exit(f"ОТКАЗ: сводка только по локальной базе, а не {host!r}")
    async with async_session_factory() as db:
        jobs = (
            await db.execute(
                text(
                    """
                    SELECT j.arena_id, j.parser_key, a.name, j.last_run_at
                    FROM ice_parser_jobs j LEFT JOIN arenas a ON a.id = j.arena_id
                    WHERE j.parser_key = ANY(:keys) ORDER BY j.arena_id
                    """
                ),
                {"keys": list(BY_KEYS)},
            )
        ).fetchall()
        print("Сводка: будущие сеансы (local_date ≥ сегодня), по арене и виду")
        for arena_id, key, name, last_run in jobs:
            rows = (
                await db.execute(
                    text(
                        """
                        SELECT kind, count(*), min(local_date), max(local_date)
                        FROM ice_sessions WHERE arena_id = :a AND local_date >= current_date
                        GROUP BY kind ORDER BY kind
                        """
                    ),
                    {"a": arena_id},
                )
            ).fetchall()
            stamp = f"{last_run:%d.%m %H:%M} UTC" if last_run else "не запускался"
            print(f"\n#{arena_id} {name or '?'} [{key}] последний прогон: {stamp}")
            if not rows:
                print("  (нет будущих сеансов)")
            for kind, n, d1, d2 in rows:
                print(f"  {kind:<18} {n:>4}  {d1:%d.%m}–{d2:%d.%m}")
            if key != "ledlife_origin_html_v1":
                continue
            detail = (
                await db.execute(
                    text(
                        """
                        SELECT kind, coalesce(hall, '—'), price_adult_minor, price_child_minor,
                               price_rental_minor, price_tiers::text, count(*)
                        FROM ice_sessions WHERE arena_id = :a AND local_date >= current_date
                        GROUP BY 1, 2, 3, 4, 5, 6 ORDER BY 1, 2, 3
                        """
                    ),
                    {"a": arena_id},
                )
            ).fetchall()
            print("  СДЮШОР: вид / зал / взр / дет / прокат / тарифы — сеансов")
            for kind, hall, ad, ch, rent, tiers, n in detail:
                t = ""
                if tiers:
                    t = "; ".join(f"{x['label']} {_money(x['minor'])}" for x in json.loads(tiers))
                print(f"    {kind:<15} {hall:<20} {_money(ad):>6} {_money(ch):>6} {_money(rent):>6}  {t or '—'}  ×{n}")


if __name__ == "__main__":
    asyncio.run(main())
