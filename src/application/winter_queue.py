"""Очередь админа «Зимой» с приоритетом (TASK-343, каталог M1, F10).

Порядок разбора (чем выше, тем раньше): споры по льду -> «точки больше нет» (под вопросом) ->
фото -> новые точки; сверка с таблицей и неподтверждённые на сезон идут отдельными строками.

Правило молчания: очередь ничего не решает сама. Фото остаётся на проверке, «под вопросом» остаётся
серой пометкой, кандидат остаётся скрытым, дифф остаётся неприменённым. Единственное, что делает
система при молчании, — повышает громкость: строка в ежедневной сводке и ``alarm`` при очереди
больше 20 или старейшей записи старше 24 часов.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import winter_admin, winter_diff

#: (kind, подпись в сводке). Порядок = приоритет.
PRIORITY: tuple[tuple[str, str], ...] = (
    ("dispute", "споры"),
    ("gone", "под вопросом"),
    ("photo_first", "фото"),
    ("new_point", "новые точки"),
)
ALARM_COUNT = 20
ALARM_AGE = timedelta(hours=24)
_RANK = {k: i for i, (k, _) in enumerate(PRIORITY)}


def _utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now


async def next_items(session: AsyncSession, limit: int = 5, *, kinds: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Открытые записи в порядке приоритета, внутри приоритета — старые раньше."""
    rows = (
        await session.execute(
            text(
                """SELECT m.id, m.kind, m.arena_id, m.ref_id, m.created_at, a.name, c.name AS city
                   FROM seasonal_moderation_items m
                   LEFT JOIN arenas a ON a.id = m.arena_id
                   LEFT JOIN cities c ON c.id = a.city_id
                   WHERE m.status = 'open' AND (CAST(:kinds AS text[]) IS NULL OR m.kind = ANY(CAST(:kinds AS text[])))
                   ORDER BY CASE m.kind WHEN 'dispute' THEN 1 WHEN 'gone' THEN 2 WHEN 'photo_first' THEN 3 ELSE 4 END,
                            m.created_at, m.id
                   LIMIT :lim"""
            ),
            {"lim": limit, "kinds": list(kinds) if kinds else None},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def queue_overview(session: AsyncSession, now: datetime | None = None) -> dict[str, Any]:
    """Сводка очереди для бота и ежедневного отчёта."""
    now = _utc(now)
    rows = (
        await session.execute(
            text("SELECT kind, count(*) AS n, min(created_at) AS oldest FROM seasonal_moderation_items WHERE status='open' GROUP BY kind")
        )
    ).all()
    by_kind = {r.kind: int(r.n) for r in rows}
    oldest_all = min((r.oldest for r in rows), default=None)
    runs = await winter_diff.pending_runs(session)
    ov = await winter_admin.season_overview(session, now)
    total = sum(by_kind.values())
    age = (now - oldest_all) if oldest_all else None
    return {
        "by_kind": by_kind,
        "total": total,
        "oldest": oldest_all.isoformat() if oldest_all else None,
        "oldest_hours": int(age.total_seconds() // 3600) if age else 0,
        "import_runs": len(runs),
        "unconfirmed": ov["unconfirmed"],
        "candidates": ov["candidates"],
        "alarm": bool(total > ALARM_COUNT or (age is not None and age > ALARM_AGE)),
    }


def queue_line(q: dict[str, Any]) -> str:
    """Строка очереди для сводки: размер, разбивка по приоритету, возраст, тревога."""
    parts = [f"{label} {q['by_kind'][kind]}" for kind, label in PRIORITY if q["by_kind"].get(kind)]
    if q["import_runs"]:
        parts.append(f"сверка {q['import_runs']}")
    head = f"очередь админа {q['total'] + q['import_runs']}"
    if parts:
        head += f" ({', '.join(parts)})"
    if q["total"]:
        head += f", старейшая {q['oldest_hours']} ч"
    if q["unconfirmed"]:
        head += f"; не подтверждено на сезон {q['unconfirmed']}"
    if q["alarm"]:
        head += "; ВНИМАНИЕ: очередь стоит, сами ничего не публикуем"
    return head
