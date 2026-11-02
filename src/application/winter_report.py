"""Сводка «Зимой» для ежедневного отчёта (TASK-344, TASK-343 п.8).

Сводка уходит в админ-бот раз в сутки в 10:00 по Минску (``tick_winter_daily_summary``, цикл ``run_winter_summary_loop``).
Свой стандарт сезонных точек: статус сезона + свежесть статуса.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.winter_photos import queue_health
from src.application.winter_queue import queue_line, queue_overview
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
    queue_info = await queue_overview(session, now)
    queue = dict(queue_info["by_kind"])
    subs = int((await session.execute(text("SELECT count(*) FROM winter_subscriptions WHERE active"))).scalar_one())
    marks24 = int((await session.execute(
        text("SELECT count(*) FROM seasonal_rink_marks WHERE created_at >= :c"), {"c": now - timedelta(hours=24)})).scalar_one())
    photos = await queue_health(session, now)
    line = (
        f"Зимой: залито {by_state.get('flooded', 0)} из {visible}, ждём заливку {by_state.get('waiting', 0)}, "
        f"давно не отмечали {by_state.get('stale', 0)}; свежий статус у {fresh}; отметок за сутки {marks24}; "
        f"{queue_line(queue_info)}; подписок {subs}"
    )
    if photos["alarm"]:
        line += f"; ВНИМАНИЕ: фото на проверке {photos['pending']}, старейшее с {photos['oldest']}"
    return {"season": ws.season_label(season), "by_state": by_state, "visible": visible, "fresh_status": fresh,
            "marks_24h": marks24, "queue": queue, "queue_info": queue_info, "subscriptions": subs, "photos": photos, "line": line}


SUMMARY_HOUR_MINSK = 10


async def tick_winter_daily_summary(
    session: AsyncSession,
    now: datetime,
    *,
    sender: Callable[..., Awaitable[bool | None]] | None = None,
) -> str | None:
    """Одно сообщение в сутки в админ-бот после 10:00 по Минску.

    Дедуп — в ``ice_ops_alerts`` (как у недельного дайджеста льда): рестарт воркера и вторая реплика
    не шлют повторно. Неудачная доставка (``False``) не помечается — следующий тик повторит.
    Флаг ``SEASONAL_RINKS_ENABLED`` проверяет цикл; здесь только время и дедуп.
    """
    from src.ingestion.alerts import send_ice_health_to_admins
    from src.ingestion.ops_alerts import KEY_WINTER_DAILY, mark_ops_alert_sent, sent_today_minsk

    if now.astimezone(ZoneInfo("Europe/Minsk")).hour < SUMMARY_HOUR_MINSK:
        return None
    if await sent_today_minsk(session, KEY_WINTER_DAILY, now=now):
        return None
    body = (await winter_summary(session, now))["line"]
    delivered = await (sender or send_ice_health_to_admins)(body, event="winter daily summary")
    if delivered is False:
        return None
    await mark_ops_alert_sent(session, KEY_WINTER_DAILY, now=now)
    return body
