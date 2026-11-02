"""Подписки «лёд рядом, 2 км» и колокольчик на точку; рассылка «залили» (TASK-343).

Правила рассылки (решения координатора 01.11 + каталог краевых случаев N*):
* повод — только подтверждённый переход в «залит» (``winter_flood_events``), не чаще 1 в сутки на точку;
* события склеиваются 5 минут, дальше одно сообщение-сводка на человека;
* не больше 1 сообщения в календарные сутки (Минск) на человека по теме; персональный колокольчик
  на конкретную точку лимит суток обходит;
* окно отправки 09:00-21:00 Минск; «залито» перепроверяется перед отправкой;
* 403 / «чат не найден» -> подписки человека ``dead``, без ретраев;
* аварийный выключатель ``winter_broadcast_enabled`` и общий ``seasonal_rinks_enabled``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.winter_links import map_allowed
from src.application.winter_public import haversine_km
from src.shared import winter_status as ws
from src.shared.config import Settings

logger = logging.getLogger(__name__)

MINSK = ZoneInfo("Europe/Minsk")
DEFAULT_RADIUS_M = 2000
MIN_RADIUS_M, MAX_RADIUS_M = 500, 5000
COALESCE_WINDOW = timedelta(minutes=5)
QUEUE_TTL = timedelta(hours=36)
SEND_FROM_H, SEND_TO_H = 9, 21

Sender = Callable[[int, str, list[int]], Awaitable[str]]  # -> "ok" | "dead" | "retry"


class SubscriptionError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def minsk_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    local = now.astimezone(MINSK)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def in_send_window(now: datetime, start_h: int = SEND_FROM_H, end_h: int = SEND_TO_H) -> bool:
    return start_h <= now.astimezone(MINSK).hour < end_h


async def subscribe_near(
    session: AsyncSession, telegram_id: int, lat: float | None, lon: float | None, radius_m: int | None = None
) -> dict[str, Any]:
    """Без координат подписку не создаём (N1): вызывающий показывает выбор города / района."""
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise SubscriptionError("no_location")
    radius = max(MIN_RADIUS_M, min(int(radius_m or DEFAULT_RADIUS_M), MAX_RADIUS_M))
    await session.execute(
        text(
            """INSERT INTO winter_subscriptions (telegram_id, kind, latitude, longitude, radius_m, active)
               VALUES (:t, 'near', :la, :lo, :r, true)
               ON CONFLICT (telegram_id) WHERE kind = 'near'
               DO UPDATE SET latitude=:la, longitude=:lo, radius_m=:r, active=true, deactivated_reason=NULL"""
        ),
        {"t": telegram_id, "la": lat, "lo": lon, "r": radius},
    )
    return {"kind": "near", "radius_m": radius}


async def subscribe_point(session: AsyncSession, telegram_id: int, arena_id: int) -> dict[str, Any]:
    ok = (
        await session.execute(
            text(
                """SELECT a.name FROM seasonal_rink_seasons s JOIN arenas a ON a.id = s.arena_id AND a.is_active
                   WHERE s.arena_id=:a AND s.season=:s AND s.state <> 'hidden'"""
            ),
            {"a": arena_id, "s": ws.current_season(datetime.now(tz=MINSK))},
        )
    ).scalar_one_or_none()
    if ok is None:
        raise SubscriptionError("not_found")
    await session.execute(
        text(
            """INSERT INTO winter_subscriptions (telegram_id, kind, arena_id, active)
               VALUES (:t, 'point', :a, true)
               ON CONFLICT (telegram_id, arena_id) WHERE kind = 'point'
               DO UPDATE SET active=true, deactivated_reason=NULL"""
        ),
        {"t": telegram_id, "a": arena_id},
    )
    return {"kind": "point", "arena_id": arena_id, "name": ok}


async def unsubscribe(session: AsyncSession, telegram_id: int, *, sub_id: int | None = None) -> int:
    """Идемпотентно: повторная отписка ничего не ломает. ``sub_id=None`` — всё («Не присылать», /stop_ice)."""
    res = await session.execute(
        text(
            """UPDATE winter_subscriptions SET active=false, deactivated_reason='unsubscribed'
               WHERE telegram_id=:t AND active AND (CAST(:sid AS bigint) IS NULL OR id = CAST(:sid AS bigint))"""
        ),
        {"t": telegram_id, "sid": sub_id},
    )
    if sub_id is None:
        await session.execute(
            text("UPDATE winter_notify_queue SET sent_at=now() WHERE telegram_id=:t AND sent_at IS NULL"),
            {"t": telegram_id},
        )
    return res.rowcount or 0


async def list_subscriptions(session: AsyncSession, telegram_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                """SELECT w.id, w.kind, w.arena_id, a.name, w.latitude, w.longitude, w.radius_m
                   FROM winter_subscriptions w LEFT JOIN arenas a ON a.id = w.arena_id
                   WHERE w.telegram_id=:t AND w.active ORDER BY w.id"""
            ),
            {"t": telegram_id},
        )
    ).all()
    return [dict(r._mapping) for r in rows]


async def fan_out_events(session: AsyncSession, now: datetime) -> int:
    """События «залили» старше 5 минут -> строки очереди получателей. Возвращает число строк."""
    events = (
        await session.execute(
            text(
                """SELECT e.id, e.arena_id, a.latitude, a.longitude, sr.geocode_precision, s.state
                   FROM winter_flood_events e
                   JOIN arenas a ON a.id = e.arena_id
                   JOIN seasonal_rinks sr ON sr.arena_id = e.arena_id
                   JOIN seasonal_rink_seasons s ON s.arena_id = e.arena_id AND s.season = e.season
                   WHERE e.fanned_out_at IS NULL AND e.flooded_at <= :cut
                   FOR UPDATE OF e SKIP LOCKED"""
            ),
            {"cut": now - COALESCE_WINDOW},
        )
    ).all()
    queued = 0
    for ev in events:
        if ev.state == ws.STATE_FLOODED:  # откатился -> рассылки не будет
            targets: dict[int, str] = {}
            points = (
                await session.execute(
                    text("SELECT telegram_id FROM winter_subscriptions WHERE kind='point' AND active AND arena_id=:a"),
                    {"a": ev.arena_id},
                )
            ).scalars().all()
            for t in points:
                targets[int(t)] = "point"
            if map_allowed(ev.geocode_precision) and ev.latitude is not None:
                nears = (
                    await session.execute(
                        text("SELECT telegram_id, latitude, longitude, radius_m FROM winter_subscriptions WHERE kind='near' AND active")
                    )
                ).all()
                for n in nears:
                    d = haversine_km(float(n.latitude), float(n.longitude), float(ev.latitude), float(ev.longitude))
                    if d * 1000 <= (n.radius_m or DEFAULT_RADIUS_M):
                        targets.setdefault(int(n.telegram_id), "near")
            for t, reason in targets.items():
                r = await session.execute(
                    text(
                        """INSERT INTO winter_notify_queue (telegram_id, arena_id, event_id, reason, created_at)
                           VALUES (:t, :a, :e, :r, :n) ON CONFLICT DO NOTHING"""
                    ),
                    {"t": t, "a": ev.arena_id, "e": ev.id, "r": reason, "n": now},
                )
                queued += r.rowcount or 0
        await session.execute(text("UPDATE winter_flood_events SET fanned_out_at=:n WHERE id=:id"), {"n": now, "id": ev.id})
    return queued


def compose_flood_message(points: list[dict[str, Any]]) -> str:
    if len(points) == 1:
        p = points[0]
        where = f" ({p['district']})" if p.get("district") else ""
        return f"Залили: {p['name']}{where}."
    lines = [f"Залито {len(points)} точки рядом:" if len(points) < 5 else f"Залито {len(points)} точек рядом:"]
    lines += [f"- {p['name']}" + (f" ({p['district']})" if p.get("district") else "") for p in points[:8]]
    return "\n".join(lines)


async def deliver_pending(session: AsyncSession, now: datetime, send: Sender) -> dict[str, int]:
    """Разослать очередь. ``send`` возвращает ok / dead / retry. Commit — на вызывающем."""
    stats = {"sent": 0, "held": 0, "dead": 0, "retry": 0, "expired": 0}
    settings = Settings()
    if not (settings.seasonal_rinks_enabled and settings.winter_broadcast_enabled) or not in_send_window(now):
        return stats
    expired = await session.execute(
        text("UPDATE winter_notify_queue SET sent_at=:n WHERE sent_at IS NULL AND created_at < :cut"),
        {"n": now, "cut": now - QUEUE_TTL},
    )
    stats["expired"] = expired.rowcount or 0
    rows = (
        await session.execute(
            text(
                """SELECT q.id, q.telegram_id, q.arena_id, q.reason, a.name, p.district, s.state
                   FROM winter_notify_queue q
                   JOIN arenas a ON a.id = q.arena_id
                   LEFT JOIN arena_profiles p ON p.arena_id = a.id
                   JOIN seasonal_rink_seasons s ON s.arena_id = q.arena_id AND s.season = :season
                   WHERE q.sent_at IS NULL ORDER BY q.telegram_id, q.id"""
            ),
            {"season": ws.current_season(now)},
        )
    ).all()
    by_user: dict[int, list[Any]] = {}
    for r in rows:
        by_user.setdefault(int(r.telegram_id), []).append(r)
    day_start, day_end = minsk_day_bounds(now)
    for tg, items in by_user.items():
        live = [i for i in items if i.state == ws.STATE_FLOODED]
        if not live:  # к моменту отправки уже не «залит»
            await session.execute(text("UPDATE winter_notify_queue SET sent_at=:n WHERE id = ANY(:ids)"), {"n": now, "ids": [i.id for i in items]})
            continue
        personal = any(i.reason == "point" for i in live)
        today = (
            await session.execute(
                text("SELECT 1 FROM winter_push_log WHERE telegram_id=:t AND sent_at >= :a AND sent_at < :b LIMIT 1"),
                {"t": tg, "a": day_start, "b": day_end},
            )
        ).first()
        if today and not personal:
            stats["held"] += 1
            continue
        points = [{"id": i.arena_id, "name": i.name, "district": i.district} for i in live]
        result = await send(tg, compose_flood_message(points), [p["id"] for p in points])
        ids = [i.id for i in items]
        if result == "ok":
            await session.execute(text("UPDATE winter_notify_queue SET sent_at=:n WHERE id = ANY(:ids)"), {"n": now, "ids": ids})
            await session.execute(
                text("INSERT INTO winter_push_log (telegram_id, arena_id, topic, sent_at) VALUES (:t, :a, 'flooded', :n)"),
                {"t": tg, "a": points[0]["id"], "n": now},
            )
            await session.execute(
                text("UPDATE winter_subscriptions SET last_notified_at=:n WHERE telegram_id=:t AND active"), {"n": now, "t": tg}
            )
            stats["sent"] += 1
        elif result == "dead":
            await session.execute(
                text("UPDATE winter_subscriptions SET active=false, deactivated_reason='dead' WHERE telegram_id=:t"), {"t": tg}
            )
            await session.execute(text("UPDATE winter_notify_queue SET sent_at=:n WHERE id = ANY(:ids)"), {"n": now, "ids": ids})
            stats["dead"] += 1
        else:
            stats["retry"] += 1
    return stats
