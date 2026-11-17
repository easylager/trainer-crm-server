"""Админское «Возвраты посетителей»: сколько людей заходило один раз, а сколько возвращалось.

Человек — ``actor_hash`` события просмотра сайта или входа в Mini App (люди, без ботов и служебных
аккаунтов). Для каждой недели (пн–вс по Минску) считаем, в скольких разных днях этой недели человек
заходил: 1 / 2 / 3–4 / 5+. Последняя строка — «за всё время»: те же корзины по всем дням, что есть в событиях.
Неделя, которая идёт, помечена ``current`` — её цифры ещё растут.

Как в Метрике: «новые» — те, чей первый визит за всю историю событий пришёлся на эту неделю, «вернувшиеся» —
остальные (были раньше). Считаем по каналам отдельно — сайт (``public_page_view``) и Mini App
(``miniapp_catalog_entry``): хэши у них разные (``pub`` и ``tg``), один человек в обоих каналах — два «человека»,
поэтому «Всего» — это сумма каналов. У первых недель истории «новых» больше, чем на деле: раньше событий нет.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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

_COUNT_KEYS = ("total", "d1", "d2", "d3_4", "d5p", "new")


def _row(total: int, d1: int, d2: int, d3_4: int, d5p: int, new: int) -> dict[str, int]:
    returned = d2 + d3_4 + d5p
    came_back = total - new
    return {
        "total": total,
        "d1": d1,
        "d2": d2,
        "d3_4": d3_4,
        "d5p": d5p,
        "returned": returned,
        "returned_pct": round(100 * returned / total) if total else 0,
        "new": new,
        "came_back": came_back,
        "came_back_pct": round(100 * came_back / total) if total else 0,
    }


def _sum_rows(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return _row(*(a[k] + b[k] for k in _COUNT_KEYS))


_CHANNELS = {"site": (KIND_PUBLIC_PAGE_VIEW,), "app": (KIND_MINIAPP_CATALOG_ENTRY,)}


async def _channel(session: AsyncSession, kinds: tuple[str, ...], now: datetime, first_monday: date) -> dict[str, Any]:
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    visits = f"""
        SELECT e.actor_hash, (e.occurred_at AT TIME ZONE 'Europe/Minsk')::date AS d
        FROM catalog_consumer_events AS e
        WHERE e.kind = ANY(:kinds) AND e.actor_hash IS NOT NULL
          AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
          AND e.occurred_at < :until {ex_sql}
        GROUP BY 1, 2
    """
    params = {
        "kinds": list(kinds),
        "until": (now + timedelta(days=1)).astimezone(timezone.utc),
        "first": first_monday,
        **ex_params,
    }
    weekly = (
        await session.execute(
            text(f"""
                WITH v AS ({visits}),
                firsts AS (SELECT actor_hash, MIN(d) AS fd FROM v GROUP BY 1),
                per_actor AS (
                    SELECT date_trunc('week', d)::date AS wk, actor_hash, COUNT(*) AS days
                    FROM v WHERE d >= :first GROUP BY 1, 2
                )
                SELECT p.wk, {_BUCKET_SQL.replace("days", "p.days")},
                       COUNT(*) FILTER (WHERE date_trunc('week', f.fd)::date = p.wk)::int AS new
                FROM per_actor AS p JOIN firsts AS f USING (actor_hash)
                GROUP BY p.wk ORDER BY p.wk
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
    zero = _row(0, 0, 0, 0, 0, 0)
    weeks = []
    for i in range(WEEKS):
        monday = first_monday + timedelta(weeks=i)
        r = by_week.get(monday)
        weeks.append({"week_start": monday, **(_row(*(int(x or 0) for x in r[1:])) if r else zero)})
    # За всё время «новые» — все, кто вообще был: вернувшихся по неделям там нет.
    all_time = _row(*(int(x or 0) for x in overall), int(overall[0] or 0))
    return {"weeks": weeks, "all_time": all_time}


def _merge(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {
        "weeks": [{"week_start": x["week_start"], **_sum_rows(x, y)} for x, y in zip(a["weeks"], b["weeks"])],
        "all_time": _sum_rows(a["all_time"], b["all_time"]),
    }


def _decorate(block: dict[str, Any], this_monday: date) -> dict[str, Any]:
    weeks = [
        {
            **w,
            "week_start": w["week_start"].isoformat(),
            "week_end": (w["week_start"] + timedelta(days=6)).isoformat(),
            "current": w["week_start"] == this_monday,
        }
        for w in block["weeks"]
    ]
    weeks.reverse()  # свежая неделя сверху
    return {"weeks": weeks, "all_time": block["all_time"]}


async def get_visitor_retention(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(MINSK)
    this_monday = (now - timedelta(days=now.weekday())).date()
    first_monday = this_monday - timedelta(weeks=WEEKS - 1)
    site = await _channel(session, _CHANNELS["site"], now, first_monday)
    app = await _channel(session, _CHANNELS["app"], now, first_monday)
    total = _decorate(_merge(site, app), this_monday)
    return {
        "metric": "visitor_retention",
        **total,
        "channels": {"site": _decorate(site, this_monday), "app": _decorate(app, this_monday)},
    }
