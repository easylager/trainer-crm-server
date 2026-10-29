"""Лента матчей Экстралиги в слоте «сейчас» главной (TASK-340, срез 3; холст — экран 11).

Порядок: матчи в городе клиента и выезды его клуба на 7 дней → (Динамо добавляет now_slot) →
«N матчей на неделе». В городе без клуба — ближайший матч области. Без города ленты нет.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import CLUBS, LEAGUE_EXTRALIGA, enabled_clubs
from src.application.hockey_event import event_href
from src.application.hockey_teams import team_card
from src.shared.config import Settings

AHEAD = timedelta(days=7)
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
_REGIONS = text("SELECT name, region FROM cities WHERE region IS NOT NULL AND name = ANY(:names)")


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


async def home_feed(
    session: AsyncSession,
    *,
    city_name: str | None,
    city_region: str | None,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    if not city_name:
        return None
    rows = await week_rows(session, now=now, settings=settings)
    if not rows:
        return None
    city = _norm(city_name)
    my_clubs = {c.name for c in CLUBS.values() if _norm(c.city) == city}
    mine = [r for r in rows if _norm(r.city) == city or r.home_team in my_clubs or r.away_team in my_clubs]
    if not mine and city_region:
        # Пинск: своего клуба нет — ближайший матч области (Брест, Барановичи).
        club_city = {c.name: c.city for c in CLUBS.values()}
        regions = {
            _norm(r.name): _norm(r.region)
            for r in (await session.execute(_REGIONS, {"names": sorted(set(club_city.values()))})).all()
        }
        region = _norm(city_region)
        near = [
            r for r in rows
            if r.starts_at > now and regions.get(_norm(club_city.get(r.home_team) or r.city)) == region
        ]
        mine = near[:1]
    mine = mine[:CITY_LIMIT]
    first_home = next((r for r in mine if _norm(r.city) == city and r.starts_at > now), None)
    cards = [
        card(r, now=now, sticker=_day_sticker(r.starts_at, now) if first_home is not None and r.id == first_home.id else None)
        for r in mine
    ]
    upcoming = sum(1 for r in rows if r.starts_at > now)
    return {"matches": cards, "week_count": upcoming, "all_href": "client-matches"}


__all__ = ["home_feed", "week_rows", "card"]
