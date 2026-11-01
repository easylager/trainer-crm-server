"""Сводка «Зимой» для ежедневного отчёта (TASK-344, TASK-343 п.8).

Механизма отчёта TASK-344 в коде пока нет — отдаём готовую функцию: словарь + строка.
Свой стандарт сезонных точек: статус сезона + свежесть статуса.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.winter_photos import queue_health
from src.shared import winter_status as ws


async def winter_summary(session: AsyncSession, now: datetime) -> dict[str, Any]:
    season = ws.current_season(now)
    rows = (await session.execute(
        text("SELECT state, count(*) FROM seasonal_rink_seasons s JOIN arenas a ON a.id=s.arena_id AND a.is_active WHERE s.season=:s GROUP BY state"),
        {"s": season})).all()
    by_state = {r[0]: int(r[1]) for r in rows}
    visible = sum(v for k, v in by_state.items() if k != "hidden")
    fresh = int((await session.execute(
        text("SELECT count(*) FROM seasonal_rink_seasons WHERE season=:s AND state IN ('flooded','waiting','stale') "
             "AND state_source IN ('engine','admin') AND state_at >= :c"),
        {"s": season, "c": now - ws.FLOODED_WINDOW})).scalar_one())
    queue = {r[0]: int(r[1]) for r in (await session.execute(
        text("SELECT kind, count(*) FROM seasonal_moderation_items WHERE status='open' GROUP BY kind"))).all()}
    subs = int((await session.execute(text("SELECT count(*) FROM winter_subscriptions WHERE active"))).scalar_one())
    marks24 = int((await session.execute(
        text("SELECT count(*) FROM seasonal_rink_marks WHERE created_at >= :c"), {"c": now - timedelta(hours=24)})).scalar_one())
    photos = await queue_health(session, now)
    line = (
        f"Зимой: залито {by_state.get('flooded', 0)} из {visible}, ждём заливку {by_state.get('waiting', 0)}, "
        f"давно не отмечали {by_state.get('stale', 0)}; свежий статус у {fresh}; отметок за сутки {marks24}; "
        f"очередь админа {sum(queue.values())}; подписок {subs}"
    )
    if photos["alarm"]:
        line += f"; ВНИМАНИЕ: фото на проверке {photos['pending']}, старейшее с {photos['oldest']}"
    return {"season": ws.season_label(season), "by_state": by_state, "visible": visible, "fresh_status": fresh,
            "marks_24h": marks24, "queue": queue, "subscriptions": subs, "photos": photos, "line": line}
