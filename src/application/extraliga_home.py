"""Лента матчей в слоте «сейчас» главной (TASK-340, срез 3; холст — экран 11).

Только домашние матчи: Экстралига, которая идёт в городе клиента, и домашние матчи Динамо-Минск
(клуб общебелорусский — во всех городах) на 14 дней. Выездов нет: страница матча открывает
только домашние матчи Динамо и Экстралигу. В окне пусто — один ближайший будущий домашний матч. «N матчей на неделе» — по-прежнему матчи Экстралиги города за 7 дней.
Игровую карточку Динамо добавляет now_slot. Без города ленты нет.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import LEAGUE_EXTRALIGA, enabled_clubs
from src.application.hockey_event import enabled as dinamo_enabled
from src.application.hockey_event import event_href
from src.application.hockey_matches import DINAMO
from src.application.hockey_teams import team_card
from src.application.site_matches import LEAGUE_KHL, place_of
from src.shared.config import Settings

AHEAD = timedelta(days=7)
# Окно ленты главной; счёт «на неделе» остаётся за AHEAD.
FEED_AHEAD = timedelta(days=14)
# Идущий и только что сыгранный матч ещё держится в ленте: счёт виден на главной.
BEHIND = timedelta(hours=3)
CITY_LIMIT = 6
TZ = ZoneInfo("Europe/Minsk")

_WEEK = text("""
    SELECT id, home_team, away_team, starts_at, status, home_score, away_score, decided_in, arena, city
    FROM hockey_matches
    WHERE league = :league AND status <> 'cancelled'
      AND starts_at >= :since AND starts_at < :until
      AND (home_team = ANY(:clubs) OR away_team = ANY(:clubs))
    ORDER BY starts_at, id
    """)

# Лента главной: Экстралига с клубами из списка и домашние матчи Динамо-Минск (КХЛ).
# ``:until`` NULL — без верхней границы (ближайший будущий матч за окном).
_FEED = text("""
    SELECT id, league, home_team, away_team, starts_at, status, home_score, away_score, decided_in, arena, city
    FROM hockey_matches
    WHERE status <> 'cancelled'
      AND starts_at >= :since AND (CAST(:until AS timestamptz) IS NULL OR starts_at < :until)
      AND (CAST(:only_scheduled AS boolean) IS NOT TRUE OR status = 'scheduled')
      AND ((league = :league AND (home_team = ANY(:clubs) OR away_team = ANY(:clubs)))
           OR (league = :khl AND :dinamo AND home_team = :dinamo_name))
    ORDER BY starts_at, id
    """)


def _norm(name: str | None) -> str:
    return (name or "").strip().lower().replace("ё", "е")


def card(row: Any, *, now: datetime, sticker: str | None = None) -> dict[str, Any]:
    final = row.status == "final" and row.home_score is not None
    return {
        "kind": "extraliga",
        "id": int(row.id),
        "href": event_href(row.id),
        "home": team_card(row.home_team),
        "away": team_card(row.away_team),
        "starts_at": row.starts_at.astimezone(timezone.utc).isoformat(),
        "arena": row.arena,
        "city": row.city,
        "live": not final and row.starts_at <= now,
        "result": (
            {"home_score": row.home_score, "away_score": row.away_score, "decided_in": row.decided_in} if final else None
        ),
        "sticker": sticker,
    }


def _day_sticker(starts_at: datetime, now: datetime) -> str | None:
    diff = (starts_at.astimezone(TZ).date() - now.astimezone(TZ).date()).days
    return "СЕГОДНЯ" if diff == 0 else "ЗАВТРА" if diff == 1 else None


async def week_rows(session: AsyncSession, *, now: datetime, settings: Settings | None = None) -> list[Any]:
    cfg = settings or Settings()  # type: ignore[call-arg]
    clubs = enabled_clubs(cfg.extraliga_clubs) if cfg.extraliga_enabled else frozenset()
    if not clubs:
        return []
    params = {"league": LEAGUE_EXTRALIGA, "since": now - BEHIND, "until": now + AHEAD, "clubs": sorted(clubs)}
    return list((await session.execute(_WEEK, params)).all())


def _feed_card(row: Any, *, now: datetime, sticker: str | None) -> dict[str, Any]:
    """Та же карточка ``card``; у Динамо места в базе нет — дома Минск-Арена."""
    out = card(row, now=now, sticker=sticker)
    if row.league == LEAGUE_KHL:
        out["arena"], out["city"] = place_of(row)
    return out


async def home_feed(
    session: AsyncSession,
    *,
    city_name: str | None,
    city_region: str | None,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Домашние матчи в городе клиента (правило A: «где посмотреть живьём») и домашние матчи Динамо-Минск.

    Выезды клубов (своего города и Динамо) и «ближайший матч области» сюда не попадают.
    ``city_region`` оставлен для совместимости вызова.
    """
    del city_region
    if not city_name:
        return None
    cfg = settings or Settings()  # type: ignore[call-arg]
    clubs = sorted(enabled_clubs(cfg.extraliga_clubs)) if cfg.extraliga_enabled else []
    dinamo = dinamo_enabled(cfg)
    if not clubs and not dinamo:
        return None
    city = _norm(city_name)
    base = {"league": LEAGUE_EXTRALIGA, "clubs": clubs, "khl": LEAGUE_KHL, "dinamo": dinamo, "dinamo_name": DINAMO}

    def mine(rows: list[Any]) -> list[Any]:
        # Экстралига — матч идёт в этом городе (город строки или клуба-хозяина): выезды клубов города отпадают.
        return [r for r in rows if r.league == LEAGUE_KHL or _norm(place_of(r)[1]) == city]

    window = mine(
        list(
            (
                await session.execute(
                    _FEED, {**base, "since": now - BEHIND, "until": now + FEED_AHEAD, "only_scheduled": False}
                )
            ).all()
        )
    )
    # Счёт «на неделе» — как раньше: матчи Экстралиги этого города за 7 дней.
    total = sum(1 for r in window if r.league != LEAGUE_KHL and r.starts_at < now + AHEAD)
    if not window:
        # В окне пусто — один ближайший будущий домашний матч, пусть и дальше двух недель.
        far = mine(
            list(
                (await session.execute(_FEED, {**base, "since": now, "until": None, "only_scheduled": True})).all()
            )
        )
        window = [r for r in far if r.starts_at > now][:1]
    if not window:
        return None
    window = window[:CITY_LIMIT]
    first_home = next((r for r in window if r.starts_at > now), None)
    cards = [
        _feed_card(
            r, now=now, sticker=_day_sticker(r.starts_at, now) if first_home is not None and r.id == first_home.id else None
        )
        for r in window
    ]
    return {
        "matches": cards,
        "week_count": total,
        "all_href": "client-matches?city=" + quote(city_name),
    }


__all__ = ["home_feed", "week_rows", "card"]
