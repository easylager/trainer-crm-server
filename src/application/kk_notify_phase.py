"""«Кто кого»: фаза игрока (TASK-426, срез 1). Считается из данных, ручных списков нет.

| фаза       | условие                                              |
|------------|------------------------------------------------------|
| off        | заблокировал бота, выключил напоминания или нажал «Не присылать» |
| new        | зарегистрировался, ходов нет                          |
| active     | последний ход — меньше 7 суток назад                  |
| cooling    | 7–13 суток назад                                      |
| lost       | 14 суток назад и раньше                               |

Сутки — календарные по Минску: ход во вторник вечером и «сегодня» в следующий вторник утром разделены ровно
семью сутками, независимо от часов. Выключенность сильнее остальных фаз. Функция чистая: время приходит
аргументом, чтобы тесты подменяли часы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.hockey_sources import MINSK_TZ

ACTIVE_DAYS = 7  # 0..6 суток без хода — активный
COOLING_DAYS = 14  # 7..13 — остывает, с 14 — отвалился


class Phase(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    COOLING = "cooling"
    LOST = "lost"
    OFF = "off"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def days_since(moment: datetime, now: datetime) -> int:
    """Целых календарных суток по Минску между ``moment`` и ``now``."""
    return (_utc(now).astimezone(MINSK_TZ).date() - _utc(moment).astimezone(MINSK_TZ).date()).days


def player_phase(*, now: datetime, last_pick_at: datetime | None, blocked: bool, opted_out: bool) -> Phase:
    if blocked or opted_out:
        return Phase.OFF
    if last_pick_at is None:
        return Phase.NEW
    days = days_since(last_pick_at, now)
    if days < ACTIVE_DAYS:
        return Phase.ACTIVE
    if days < COOLING_DAYS:
        return Phase.COOLING
    return Phase.LOST


@dataclass(frozen=True)
class PlayerFacts:
    player_key: int
    registered_at: datetime
    last_pick_at: datetime | None
    opted_out: bool
    blocked: bool
    paused_until: datetime | None = None
    # Согласие на новые сообщения: None — не спрашивали, True — согласен, False — нажал «Не присылать».
    consent: bool | None = None

    def phase(self, now: datetime) -> Phase:
        return player_phase(
            now=now, last_pick_at=self.last_pick_at, blocked=self.blocked, opted_out=self.opted_out
        )


_FACTS = text("""
    SELECT pl.player_key, pl.created_at AS registered_at,
           (SELECT MAX(hp.picked_at) FROM hockey_picks AS hp
            WHERE hp.player_key = pl.player_key AND hp.picked_at <= :as_of) AS last_pick_at,
           (NOT COALESCE(pr.remind, true) OR pr.notify_consent IS FALSE) AS opted_out,
           (pr.bot_blocked_at IS NOT NULL) AS blocked,
           pr.notify_paused_until AS paused_until,
           pr.notify_consent AS consent
    FROM hockey_players AS pl
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = pl.player_key
    WHERE pl.created_at <= :as_of AND (CAST(:only AS BIGINT) IS NULL OR pl.player_key = :only)
    ORDER BY pl.player_key
    """)


async def load_player_facts(
    session: AsyncSession, *, as_of: datetime, only: int | None = None
) -> list[PlayerFacts]:
    """Факты по всем игрокам на момент ``as_of``. Ходы и регистрация учитываются «как были тогда»;
    блокировка и «не присылать» — текущие (истории этих отметок в базе нет)."""
    rows = (await session.execute(_FACTS, {"as_of": _utc(as_of), "only": only})).all()
    return [
        PlayerFacts(
            player_key=r.player_key,
            registered_at=r.registered_at,
            last_pick_at=r.last_pick_at,
            opted_out=bool(r.opted_out),
            blocked=bool(r.blocked),
            paused_until=r.paused_until,
            consent=r.consent,
        )
        for r in rows
    ]


async def load_one(session: AsyncSession, player_key: int, *, as_of: datetime) -> PlayerFacts | None:
    found = await load_player_facts(session, as_of=as_of, only=player_key)
    return found[0] if found else None


__all__ = ["Phase", "PlayerFacts", "days_since", "load_one", "load_player_facts", "player_phase"]
