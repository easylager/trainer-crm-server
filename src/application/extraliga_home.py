"""Лента матчей Экстралиги в слоте «сейчас» главной (TASK-340, срез 3; холст — экран 11).

Порядок: матчи, которые идут в городе клиента, на 14 дней → (Динамо добавляет now_slot) →
«N матчей на неделе» по этому городу (счёт — за 7 дней). Выездов и «матчей области» нет. Без города
ленты нет. В 14 днях пусто — ``far``: один ближайший будущий матч города, now_slot решает, нужен ли он.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.extraliga import LEAGUE_EXTRALIGA, enabled_clubs
from src.application.hockey_event import event_href
from src.application.hockey_teams import team_card
from src.shared.config import Settings

AHEAD = timedelta(days=7)
# Окно ленты главной — общее с Динамо (hockey_hub.UPCOMING_AHEAD, владелец 2026-11-11).
HUB_AHEAD = timedelta(days=14)
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

# Ближайший будущий матч каждого города — на него ещё можно пойти. Город сверяем в Python (_norm):
# lower() кириллицы в Postgres зависит от локали базы.
_FAR = text("""
    SELECT DISTINCT ON (city) id, home_team, away_team, starts_at, status, home_score, away_score, decided_in,
           arena, city
    FROM hockey_matches
    WHERE league = :league AND status = 'scheduled' AND starts_at > :now AND city IS NOT NULL
      AND (home_team = ANY(:clubs) OR away_team = ANY(:clubs))
    ORDER BY city, starts_at, id
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


def _clubs(settings: Settings | None) -> frozenset[str]:
    cfg = settings or Settings()  # type: ignore[call-arg]
    return enabled_clubs(cfg.extraliga_clubs) if cfg.extraliga_enabled else frozenset()


async def week_rows(
    session: AsyncSession, *, now: datetime, settings: Settings | None = None, ahead: timedelta = AHEAD
) -> list[Any]:
    clubs = _clubs(settings)
    if not clubs:
        return []
    params = {"league": LEAGUE_EXTRALIGA, "since": now - BEHIND, "until": now + ahead, "clubs": sorted(clubs)}
    return list((await session.execute(_WEEK, params)).all())


async def home_feed(
    session: AsyncSession,
    *,
    city_name: str | None,
    city_region: str | None,
    now: datetime,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    """Матчи, которые идут в городе клиента (правило A: «где посмотреть живьём»).

    Выезды местного клуба и «ближайший матч области» сюда не попадают: в слоте только то, что можно
    увидеть в этом городе. ``city_region`` оставлен для совместимости вызова.
    """
    del city_region
    if not city_name:
        return None
    rows = await week_rows(session, now=now, settings=settings, ahead=HUB_AHEAD)
    city = _norm(city_name)
    mine = [r for r in rows if _norm(r.city) == city]
    all_href = "client-matches?city=" + quote(city_name)
    if not mine:
        clubs = _clubs(settings)
        nearest = (
            (await session.execute(_FAR, {"league": LEAGUE_EXTRALIGA, "now": now, "clubs": sorted(clubs)})).all()
            if clubs
            else []
        )
        far = min((r for r in nearest if _norm(r.city) == city), key=lambda r: r.starts_at, default=None)
        if far is None:
            return None
        return {"matches": [], "far": card(far, now=now), "week_count": 0, "all_href": all_href}
    total = sum(1 for r in mine if r.starts_at < now + AHEAD)
    mine = mine[:CITY_LIMIT]
    first_home = next((r for r in mine if r.starts_at > now), None)
    cards = [
        card(r, now=now, sticker=_day_sticker(r.starts_at, now) if first_home is not None and r.id == first_home.id else None)
        for r in mine
    ]
    return {
        "matches": cards,
        "week_count": total,
        "all_href": all_href,
    }


__all__ = ["home_feed", "week_rows", "card"]
