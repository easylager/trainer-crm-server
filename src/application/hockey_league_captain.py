"""Право капитана «Кто кого» (TASK-432): капитан вечера выдаёт одну вещь экипировки.

Капитан — лучший за игровой день лиги (правило — в ``hockey_league_evening``, зеркало кепки дня). Пока вечер
последний сыгранный в лиге и лига не закончилась, капитан выдаёт одну вещь любому участнику, в том числе себе, и
может поменять вещь или получателя. Капитанов несколько — выдаёт тот, кто успел первым, менять может только он.

Выдача хранится за (лига, вечер) и проверяется при каждом чтении:

* капитан всё ещё капитан этого вечера (итог матча поправили — выдача снимается, право у нового капитана);
* получатель всё ещё в лиге (вышел — вещь не показываем);
* вечер — последний сыгранный в лиге, лига не закончилась (следующий вечер сыгран — вещь снята).

Голова в лиге: выданная вещь → иначе кепка дня, если в кепке → иначе пусто. Снаружи лиги (общая таблица) — только
выданные вещи, последняя выданная сверху; ни кепки, ни капитана; имя лиги не показываем.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.hockey_league_evening import (
    _MEMBER_BY_PID,
    MISS,
    NONE,
    DayCap,
    DayMatch,
    DayRow,
    _utc,
    cap_of_rows,
    day_complete,
    day_matches,
    day_rows,
    game_day,
    last_complete_day,
    league_members,
    mark,
)

# Коллекция «Экипировка капитана»: без категорий, все бесплатно (владелец 2026-11-19). Порядок — как в выборе.
OUTFITS = ("wanted", "half", "bag", "sieve", "scorehat", "snorkel", "hardhat", "curlers", "foil", "bucket")
HEAD_CAP = "cap"  # кепка дня на голове, когда капитан ничего не выдал этому человеку


class OutfitRefused(ValueError):
    """Нельзя: неизвестная вещь или человек не в лиге (текст — для человека)."""


class NotCaptain(PermissionError):
    """Выдаёт только капитан этого вечера."""


class RightClosed(Exception):
    """Вечер не сыгран, уже не последний сыгранный или лига закончилась."""


class AlreadyGiven(Exception):
    """Другой капитан этого вечера уже выдал экипировку (``name`` — кто)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def captain_enabled() -> bool:
    """Право капитана включено настройкой ``KK_CAPTAIN_ENABLED`` (по умолчанию включено)."""
    from src.shared.config import Settings

    return bool(Settings().kk_captain_enabled)  # type: ignore[call-arg]


@dataclass(frozen=True)
class Award:
    captain_key: int
    captain_name: str
    to_key: int
    item: str
    updated_at: datetime


_AWARD = text("""
    SELECT o.captain_key, pl.display_name AS captain_name, o.to_key, o.item, o.updated_at
    FROM hockey_league_outfits AS o
    JOIN hockey_players AS pl ON pl.player_key = o.captain_key
    WHERE o.league_id = :league_id AND o.day = :day
    """)

_UPSERT = text("""
    INSERT INTO hockey_league_outfits (league_id, day, captain_key, to_key, item, updated_at)
    VALUES (:league_id, :day, :captain_key, :to_key, :item, clock_timestamp())
    ON CONFLICT (league_id, day) DO UPDATE
    SET captain_key = EXCLUDED.captain_key, to_key = EXCLUDED.to_key, item = EXCLUDED.item,
        updated_at = EXCLUDED.updated_at
    WHERE hockey_league_outfits.captain_key = EXCLUDED.captain_key
       OR NOT (hockey_league_outfits.captain_key = ANY(:captains))
    RETURNING captain_key
    """)

# Последняя выдача в каждой лиге этих людей: более ранние вечера уже точно не последние сыгранные.
_LATEST_AWARDS = text("""
    SELECT DISTINCT ON (o.league_id) o.league_id, o.day, o.to_key
    FROM hockey_league_outfits AS o
    WHERE o.league_id IN (SELECT league_id FROM hockey_league_members WHERE player_key = ANY(:keys))
    ORDER BY o.league_id, o.day DESC
    """)


async def day_award(session: AsyncSession, league_id: int, day: date) -> Award | None:
    r = (await session.execute(_AWARD, {"league_id": league_id, "day": day})).one_or_none()
    return None if r is None else Award(r.captain_key, r.captain_name, r.to_key, r.item, r.updated_at)


def award_valid(award: Award | None, cap: DayCap, members: set[int]) -> bool:
    return award is not None and award.captain_key in cap.captains and award.to_key in members


def outfit_numbers(row: DayRow, matches: list[DayMatch]) -> dict:
    """Цифры для вещей с цифрами: «ЗА 0 ИЗ 4» на плакате и счёт матча, где всё пошло не так, на шапке-табло.

    Матч — первый промах вечера; промахов нет — первый матч без хода; иначе последний матч."""
    marks = [(mark(row.picks.get(m.id), m), m) for m in matches]
    worst = next((m for k, m in marks if k == MISS), None) or next((m for k, m in marks if k == NONE), None)
    worst = worst or (matches[-1] if matches else None)
    score = ""
    if worst is not None and worst.home_score is not None and worst.away_score is not None:
        score = f"{worst.home_score}:{worst.away_score}"
    return {"stat": f"ЗА {row.hits} ИЗ {len(matches)}", "score": score}


@dataclass
class EveningState:
    """Вечер лиги глазами экипировки: капитаны, кепка, действительная выдача и голова каждого участника."""

    day: date
    cap: DayCap
    rows: list[DayRow]
    matches: list[DayMatch]
    award: Award | None  # только действительная
    current: bool  # вечер — последний сыгранный, лига идёт: выдача видна и её можно менять

    def head(self, key: int, *, enabled: bool) -> dict | None:
        if enabled and self.award is not None and self.award.to_key == key:
            row = next(r for r in self.rows if r.member.player_key == key)
            return {"item": self.award.item, **outfit_numbers(row, self.matches)}
        if key in self.cap.holders:
            return {"item": HEAD_CAP}
        return None


async def evening_state(
    session: AsyncSession,
    league,
    day: date,
    *,
    now: datetime,
    rows: list[DayRow] | None = None,
    matches: list[DayMatch] | None = None,
    last_day: date | None = None,
) -> EveningState:
    """Состояние вечера ``day``. ``rows``/``matches``/``last_day`` (последний сыгранный вечер лиги) — если
    вызывающий их уже посчитал."""
    if matches is None:
        matches = await day_matches(session, league, day)
    if rows is None:
        rows = await day_rows(session, league.id, await league_members(session, league.id, now=now), matches)
    cap = cap_of_rows(rows, matches)
    award = await day_award(session, league.id, day)
    if not award_valid(award, cap, {r.member.player_key for r in rows}):
        award = None
    if day_complete(matches) and _utc(league.ends_at) > _utc(now):
        current = (last_day or await last_complete_day(session, league, now=now)) == day
    else:
        current = False
    return EveningState(day=day, cap=cap, rows=rows, matches=matches, award=award, current=current)


async def current_state(session: AsyncSession, league, *, now: datetime) -> EveningState | None:
    """Что сейчас «на головах» в лиге: последний сыгранный вечер (нет такого — ``None``)."""
    day = await last_complete_day(session, league, now=now)
    return None if day is None else await evening_state(session, league, day, now=now, last_day=day)


async def set_outfit(
    session: AsyncSession, *, league, captain_key: int, to_pid: str, item: str, day: date, now: datetime
) -> None:
    """Выдать или поменять экипировку вечера ``day``. Участие ``captain_key`` проверяет вызывающий.

    ``OutfitRefused`` — неизвестная вещь или получатель не в лиге; ``RightClosed`` — вечер не последний сыгранный
    или лига закончилась; ``NotCaptain`` — не капитан этого вечера; ``AlreadyGiven`` — выдал другой капитан."""
    if item not in OUTFITS:
        raise OutfitRefused("Такой вещи нет")
    to_key = (await session.execute(_MEMBER_BY_PID, {"league_id": league.id, "pid": to_pid})).scalar_one_or_none()
    if to_key is None:
        raise OutfitRefused("Этого человека нет в лиге")
    if game_day(now) < day:
        raise RightClosed(day)
    state = await evening_state(session, league, day, now=now)
    if not state.current:
        raise RightClosed(day)
    if captain_key not in state.cap.captains:
        raise NotCaptain()
    if state.award is not None and state.award.captain_key != captain_key:
        raise AlreadyGiven(state.award.captain_name)
    # Два капитана жмут одновременно: оба прочли «выдачи нет», запись решает. Перезаписать можно только свою выдачу
    # или выдачу того, кто уже не капитан; иначе первый успел — второму AlreadyGiven.
    params = {
        "league_id": league.id,
        "day": day,
        "captain_key": captain_key,
        "to_key": to_key,
        "item": item,
        "captains": list(state.cap.captains),
    }
    if (await session.execute(_UPSERT, params)).scalar_one_or_none() is None:
        award = await day_award(session, league.id, day)
        raise AlreadyGiven(award.captain_name if award else "")


async def outside_outfits(session: AsyncSession, player_keys: list[int], *, now: datetime) -> dict[int, dict]:
    """Экипировка снаружи лиг (общая таблица): ``{игрок: {item, stat, score, items}}`` только у тех, на ком она есть.

    ``item`` — последняя выданная из действующих; ``items`` — все действующие (с цифрами), последние первыми,
    одинаковые вещи из разных лиг вместе (``n``). Имени лиги и капитана здесь нет: снаружи — «от капитана лиги»."""
    if not player_keys or not captain_enabled():
        return {}
    from src.application.hockey_leagues import _LEAGUE_COLUMNS, _league

    keys = set(player_keys)
    latest = [r for r in (await session.execute(_LATEST_AWARDS, {"keys": list(keys)})).all() if r.to_key in keys]
    if not latest:
        return {}
    leagues_sql = text(f"SELECT {_LEAGUE_COLUMNS} FROM hockey_leagues WHERE id = ANY(:ids) AND ends_at > :now")
    params = {"ids": [r.league_id for r in latest], "now": _utc(now)}
    leagues = {lg.id: lg for lg in (_league(r) for r in (await session.execute(leagues_sql, params)).all())}
    worn: dict[int, list[tuple[datetime, dict]]] = {}
    for r in latest:
        league = leagues.get(r.league_id)
        if league is None:
            continue
        state = await evening_state(session, league, r.day, now=now)
        if not state.current or state.award is None:
            continue
        head = state.head(state.award.to_key, enabled=True)
        worn.setdefault(state.award.to_key, []).append((_utc(state.award.updated_at), head))  # type: ignore[arg-type]
    out: dict[int, dict] = {}
    for key, found in worn.items():
        found.sort(key=lambda x: x[0], reverse=True)
        listed: dict[str, dict] = {}
        for _, head in found:
            if head["item"] in listed:
                listed[head["item"]]["n"] += 1
            else:
                listed[head["item"]] = {**head, "n": 1}
        out[key] = {**found[0][1], "items": list(listed.values())}
    return out


__all__ = [
    "AlreadyGiven",
    "Award",
    "EveningState",
    "HEAD_CAP",
    "NotCaptain",
    "OUTFITS",
    "OutfitRefused",
    "RightClosed",
    "award_valid",
    "captain_enabled",
    "current_state",
    "day_award",
    "evening_state",
    "outfit_numbers",
    "outside_outfits",
    "set_outfit",
]
