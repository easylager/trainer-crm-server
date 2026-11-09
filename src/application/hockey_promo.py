"""Рекламный вход в «Кто кого»: метка источника, заходы без ключа игрока, срез по меткам."""

from __future__ import annotations

import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_SRC_RE = re.compile(r"^[A-Za-z0-9]{2,16}$")


def clean_src(value: str | None) -> str | None:
    """Метка из ссылки: 2–16 латиница/цифры, в нижнем регистре; всё остальное — None (игнорируем)."""
    candidate = (value or "").strip()
    return candidate.lower() if _SRC_RE.fullmatch(candidate) else None


_ENTRY = text("INSERT INTO hockey_entry_events (src) VALUES (:src)")

# Метки — объединение заходов и первых ходов. «Вернулся» — ходы, созданные в разные минские сутки.
_REPORT = text("""
    WITH entries AS (
        SELECT src, count(*) AS n FROM hockey_entry_events GROUP BY src
    ),
    players AS (
        SELECT p.first_src AS src,
               count(*) AS new_players,
               count(*) FILTER (WHERE s.picks > 0) AS picked,
               count(*) FILTER (WHERE s.days > 1) AS returned
        FROM hockey_players p
        LEFT JOIN LATERAL (
            SELECT count(*) AS picks,
                   count(DISTINCT (k.created_at AT TIME ZONE 'Europe/Minsk')::date) AS days
            FROM hockey_picks k WHERE k.player_key = p.player_key
        ) s ON true
        WHERE p.first_src IS NOT NULL
        GROUP BY p.first_src
    )
    SELECT COALESCE(e.src, p.src) AS src,
           COALESCE(e.n, 0) AS entries,
           COALESCE(p.new_players, 0) AS new_players,
           COALESCE(p.picked, 0) AS picked,
           COALESCE(p.returned, 0) AS returned
    FROM entries e FULL JOIN players p ON p.src = e.src
    ORDER BY COALESCE(p.new_players, 0) DESC, COALESCE(e.n, 0) DESC, 1
    """)


async def record_entry(session: AsyncSession, src: str | None) -> bool:
    """Один заход по метке. Невалидная метка не пишется; сбой записи не ломает вход в игру."""
    label = clean_src(src)
    if label is None:
        return False
    try:
        async with session.begin_nested():
            await session.execute(_ENTRY, {"src": label})
    except Exception:  # noqa: BLE001
        logger.warning("hockey entry event not recorded src=%s", label, exc_info=True)
        return False
    return True


async def promo_report(session: AsyncSession) -> list[dict]:
    """По каждой метке: заходов, новых игроков, сделавших ход, вернувшихся в другой день."""
    rows = (await session.execute(_REPORT)).all()
    return [
        {
            "src": row.src,
            "entries": int(row.entries),
            "new_players": int(row.new_players),
            "picked": int(row.picked),
            "returned": int(row.returned),
        }
        for row in rows
    ]


__all__ = ["clean_src", "promo_report", "record_entry"]
