"""Админское «Возвраты посетителей»: сколько людей заходило один раз, а сколько возвращалось.

Человек — ``actor_hash`` события просмотра сайта или входа в Mini App (люди, без ботов и служебных
аккаунтов). Для каждой недели (пн–вс по Минску) считаем, в скольких разных днях этой недели человек
заходил: 1 / 2 / 3–4 / 5+. Последняя строка — «за всё время»: те же корзины по всем дням, что есть в событиях.
Неделя, которая идёт, помечена ``current`` — её цифры ещё растут.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_consumer_events import (
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_PAGE_VIEW,
    catalog_actor_exclusion_sql,
)

WEEKS = 8
MINSK = timezone(timedelta(hours=3))  # Минск без перехода на летнее время
BUCKETS = ("d1", "d2", "d3_4", "d5p")

_BUCKET_SQL = """
    COUNT(*)::int AS total,
    COUNT(*) FILTER (WHERE days = 1)::int AS d1,
    COUNT(*) FILTER (WHERE days = 2)::int AS d2,
    COUNT(*) FILTER (WHERE days BETWEEN 3 AND 4)::int AS d3_4,
    COUNT(*) FILTER (WHERE days >= 5)::int AS d5p
"""


def _row(total: int, d1: int, d2: int, d3_4: int, d5p: int) -> dict[str, int]:
    returned = d2 + d3_4 + d5p
    return {
        "total": total,
        "d1": d1,
        "d2": d2,
        "d3_4": d3_4,
        "d5p": d5p,
        "returned": returned,
        "returned_pct": round(100 * returned / total) if total else 0,
    }


async def get_visitor_retention(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(MINSK)
    this_monday = (now - timedelta(days=now.weekday())).date()
    first_monday = this_monday - timedelta(weeks=WEEKS - 1)
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    visits = f"""
        SELECT e.actor_hash, (e.occurred_at AT TIME ZONE 'Europe/Minsk')::date AS d
        FROM catalog_consumer_events AS e
        WHERE e.kind IN (:pv, :mini) AND e.actor_hash IS NOT NULL
          AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
          AND e.occurred_at < :until {ex_sql}
        GROUP BY 1, 2
    """
    params = {
        "pv": KIND_PUBLIC_PAGE_VIEW,
        "mini": KIND_MINIAPP_CATALOG_ENTRY,
        "until": (now + timedelta(days=1)).astimezone(timezone.utc),
        "first": first_monday,
        **ex_params,
    }
    weekly = (
        await session.execute(
            text(f"""
                WITH v AS ({visits}),
                per_actor AS (
                    SELECT date_trunc('week', d)::date AS wk, actor_hash, COUNT(*) AS days
                    FROM v WHERE d >= :first GROUP BY 1, 2
                )
                SELECT wk, {_BUCKET_SQL} FROM per_actor GROUP BY wk ORDER BY wk
                """),
            params,
        )
    ).all()
    overall = (
        await session.execute(
            text(f"""
                WITH v AS ({visits}),
                per_actor AS (SELECT actor_hash, COUNT(*) AS days FROM v GROUP BY 1)
                SELECT {_BUCKET_SQL} FROM per_actor
                """),
            params,
        )
    ).one()
    by_week = {r[0]: r for r in weekly}
    rows: list[dict[str, Any]] = []
    for i in range(WEEKS):
        monday = first_monday + timedelta(weeks=i)
        r = by_week.get(monday)
        counts = _row(*(int(x or 0) for x in r[1:])) if r else _row(0, 0, 0, 0, 0)
        rows.append(
            {
                "week_start": monday.isoformat(),
                "week_end": (monday + timedelta(days=6)).isoformat(),
                "current": monday == this_monday,
                **counts,
            }
        )
    rows.reverse()  # свежая неделя сверху
    return {"metric": "visitor_retention", "weeks": rows, "all_time": _row(*(int(x or 0) for x in overall))}
