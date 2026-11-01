"""«Были? Как лёд?» через сутки после клика «Маршрут» (TASK-343).

Только после «Маршрута» (не после «Ждать»). Потолок: 1 зимнее сообщение в сутки на человека
(вопрос ниже приоритетом, чем рассылка «залили»), 1 вопрос в 3 дня, после 2 игнорирований
подряд — пауза 14 дней, окно отправки 10:00-20:00 Минск. «Не был» — по точке навсегда,
«Не спрашивать совсем» — глобально. Ответ без гео весит 0,5.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.winter_marks import MarkError, record_mark
from src.application.winter_subscriptions import MINSK, in_send_window, minsk_day_bounds
from src.shared import winter_status as ws

ASK_DELAY = timedelta(hours=24)
ASK_GAP = timedelta(days=3)
IGNORE_AFTER = timedelta(hours=48)
PAUSE = timedelta(days=14)
ANSWER_WEIGHT = 0.5
ASK_FROM_H, ASK_TO_H = 10, 20


def align_to_window(moment: datetime) -> datetime:
    local = moment.astimezone(MINSK)
    if local.hour < ASK_FROM_H:
        local = local.replace(hour=ASK_FROM_H, minute=0, second=0, microsecond=0)
    elif local.hour >= ASK_TO_H:
        local = (local + timedelta(days=1)).replace(hour=ASK_FROM_H, minute=0, second=0, microsecond=0)
    return local


async def _prefs(session: AsyncSession, tg: int):
    await session.execute(text("INSERT INTO winter_user_prefs (telegram_id) VALUES (:t) ON CONFLICT DO NOTHING"), {"t": tg})
    return (await session.execute(text("SELECT * FROM winter_user_prefs WHERE telegram_id=:t"), {"t": tg})).one()


async def schedule_ask(session: AsyncSession, telegram_id: int, arena_id: int, now: datetime) -> bool:
    """Вызывается кликом «Маршрут». False — спрашивать не будем."""
    prefs = await _prefs(session, telegram_id)
    if prefs.no_ask or (prefs.paused_until and prefs.paused_until > now):
        return False
    seen = (
        await session.execute(
            text("SELECT 1 FROM winter_asks WHERE telegram_id=:t AND (arena_id=:a OR status IN ('pending','asked')) LIMIT 1"),
            {"t": telegram_id, "a": arena_id},
        )
    ).first()
    if seen:
        return False
    await session.execute(
        text("INSERT INTO winter_asks (telegram_id, arena_id, via, due_at) VALUES (:t, :a, 'route', :d)"),
        {"t": telegram_id, "a": arena_id, "d": align_to_window(now + ASK_DELAY)},
    )
    return True


async def expire_ignored(session: AsyncSession, now: datetime) -> int:
    rows = (
        await session.execute(
            text("UPDATE winter_asks SET status='dismissed' WHERE status='asked' AND asked_at < :c RETURNING telegram_id"),
            {"c": now - IGNORE_AFTER},
        )
    ).scalars().all()
    for tg in rows:
        await session.execute(
            text(
                """UPDATE winter_user_prefs SET ignored_streak = ignored_streak + 1,
                   paused_until = CASE WHEN ignored_streak + 1 >= 2 THEN :p ELSE paused_until END,
                   ignored_streak = CASE WHEN ignored_streak + 1 >= 2 THEN 0 ELSE ignored_streak + 1 END
                   WHERE telegram_id=:t"""
            ),
            {"t": tg, "p": now + PAUSE},
        )
    return len(rows)


async def due_asks(session: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    """Вопросы к отправке сейчас; помечаются ``asked``. Commit — на вызывающем."""
    if not in_send_window(now, ASK_FROM_H, ASK_TO_H):
        return []
    rows = (
        await session.execute(
            text(
                """SELECT k.id, k.telegram_id, k.arena_id, a.name FROM winter_asks k JOIN arenas a ON a.id=k.arena_id
                   WHERE k.status='pending' AND k.due_at <= :n ORDER BY k.due_at"""
            ),
            {"n": now},
        )
    ).all()
    day_a, day_b = minsk_day_bounds(now)
    out: list[dict[str, Any]] = []
    for r in rows:
        prefs = await _prefs(session, int(r.telegram_id))
        if prefs.no_ask or (prefs.paused_until and prefs.paused_until > now):
            await session.execute(text("UPDATE winter_asks SET status='dismissed' WHERE id=:i"), {"i": r.id})
            continue
        if prefs.last_ask_at and now - prefs.last_ask_at < ASK_GAP:
            continue
        busy = (
            await session.execute(
                text("SELECT 1 FROM winter_push_log WHERE telegram_id=:t AND sent_at >= :a AND sent_at < :b LIMIT 1"),
                {"t": r.telegram_id, "a": day_a, "b": day_b},
            )
        ).first()
        if busy:
            continue
        await session.execute(text("UPDATE winter_asks SET status='asked', asked_at=:n WHERE id=:i"), {"n": now, "i": r.id})
        await session.execute(text("UPDATE winter_user_prefs SET last_ask_at=:n WHERE telegram_id=:t"), {"n": now, "t": r.telegram_id})
        await session.execute(
            text("INSERT INTO winter_push_log (telegram_id, arena_id, topic, sent_at) VALUES (:t, :a, 'ask', :n)"),
            {"t": r.telegram_id, "a": r.arena_id, "n": now},
        )
        out.append({"ask_id": int(r.id), "telegram_id": int(r.telegram_id), "arena_id": int(r.arena_id), "name": r.name})
    return out


async def answer_ask(session: AsyncSession, ask_id: int, telegram_id: int, answer: str, now: datetime) -> str:
    """answer: flooded | bad | not_flooded | not_been | stop. Идемпотентно по статусу вопроса."""
    row = (
        await session.execute(
            text("SELECT arena_id, status FROM winter_asks WHERE id=:i AND telegram_id=:t FOR UPDATE"),
            {"i": ask_id, "t": telegram_id},
        )
    ).first()
    if row is None:
        return "unknown"
    if row.status == "answered" or (row.status == "dismissed" and answer != "stop"):
        return "already"
    if answer == "stop":
        await session.execute(text("UPDATE winter_asks SET status='dismissed' WHERE id=:i"), {"i": ask_id})
        await _prefs(session, telegram_id)
        await session.execute(text("UPDATE winter_user_prefs SET no_ask=true, updated_at=now() WHERE telegram_id=:t"), {"t": telegram_id})
        return "stopped"
    if answer == "not_been":
        await session.execute(text("UPDATE winter_asks SET status='dismissed', answered_at=:n WHERE id=:i"), {"n": now, "i": ask_id})
        return "not_been"
    if answer not in ws.VALUES[ws.KIND_ICE]:
        return "bad_answer"
    try:
        await record_mark(
            session, arena_id=int(row.arena_id), kind=ws.KIND_ICE, value=answer, source=ws.SOURCE_TELEGRAM,
            actor=f"tg:{telegram_id}", telegram_id=telegram_id, weight=ANSWER_WEIGHT, now=now,
        )
    except MarkError:
        return "gone"
    await session.execute(text("UPDATE winter_asks SET status='answered', answered_at=:n WHERE id=:i"), {"n": now, "i": ask_id})
    await session.execute(text("UPDATE winter_user_prefs SET ignored_streak=0 WHERE telegram_id=:t"), {"t": telegram_id})
    return "ok"
