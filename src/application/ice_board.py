"""TASK-438: вкладка «Поиск» — лента сеансов города по времени и матчи в городе.

Правила отбора сеансов — те же, что у «Лёд сегодня» (``ice_city_day``): видимая арена,
сезон не закрыт, сеанс active, ещё не начался. Отличие одно — виды шире: кроме массового
катания в ленту идут хоккейный и фигурный свободный лёд.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_media import attach_arena_media_payloads
from src.application.ice_city_day import (
    DEFAULT_TIMEZONE,
    ICE_CITY_DAY_FROM_SQL,
    ICE_CITY_DAY_SESSION_WHERE_SQL,
    _city_timezone,
    _hhmm,
    _local_today,
    format_price_minor,
)
from src.application.ice_session_use_cases import STATUS_ACTIVE
from src.application.site_matches import in_city, match_card, visible_rows
from src.shared.ice_discovery_scope import public_scope_params

MAX_DAYS = 7

# Вид сеанса → группа ленты.
KIND_GROUP: dict[str, str] = {
    "public_skate": "skate",
    "open_ice": "skate",
    "family_skate": "skate",
    "hockey_practice": "hockey",
    "figure_free": "figure",
}

_BASE_KINDS = "s.kind IN ('public_skate', 'open_ice')"
assert _BASE_KINDS in ICE_CITY_DAY_SESSION_WHERE_SQL, "правила «Лёд сегодня» поменялись — сверить ленту"
_BOARD_WHERE_SQL = ICE_CITY_DAY_SESSION_WHERE_SQL.replace(
    _BASE_KINDS, "s.kind IN (" + ", ".join(f"'{k}'" for k in KIND_GROUP) + ")"
)

_SESSIONS_SQL = text(
    f"""
SELECT
    a.id            AS arena_id,
    a.name          AS arena_name,
    p.district      AS district,
    s.id            AS session_id,
    s.kind          AS kind,
    s.local_date    AS local_date,
    s.starts_at_local,
    s.ends_at_local,
    s.price_adult_minor,
    s.price_rental_minor,
    s.currency_code,
    s.session_label,
    s.age_note
{ICE_CITY_DAY_FROM_SQL}
WHERE a.city_id = :cid
  AND s.local_date >= :day_from AND s.local_date <= :day_to
  {_BOARD_WHERE_SQL}
ORDER BY s.local_date, s.starts_at_local, a.name, s.id
"""
)


class CityNotFound(LookupError):
    pass


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — битый пояс в профиле не роняет ленту
        return ZoneInfo(DEFAULT_TIMEZONE)


async def _arena_thumbs(session: AsyncSession, arena_ids: list[int]) -> dict[int, str | None]:
    """Превью арен одним запросом — тот же ``thumb``, что в списке «Льда»."""
    items: list[dict[str, Any]] = [{"id": aid} for aid in arena_ids]
    await attach_arena_media_payloads(session, items)
    out: dict[int, str | None] = {}
    for item in items:
        hero = item.get("hero")
        variants = hero.get("variants") if isinstance(hero, dict) else None
        thumb = (variants.get("thumb") or variants.get("card")) if isinstance(variants, dict) else None
        out[int(item["id"])] = thumb or None
    return out


async def _matches(
    session: AsyncSession, *, city_name: str, day_from: date, day_to: date, tz: ZoneInfo
) -> list[dict[str, Any]]:
    """Матчи, которые проходят в городе (``site_matches.in_city``): по месту матча, не по клубу."""
    since = datetime.combine(day_from, datetime.min.time(), tz).astimezone(timezone.utc)
    until = datetime.combine(day_to + timedelta(days=1), datetime.min.time(), tz).astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    out: list[dict[str, Any]] = []
    for row, arena in await visible_rows(session, since=since, until=until):
        if not in_city(row, city_name):
            continue
        card = match_card(row, now=now, arena=arena)
        out.append(
            {
                "match_id": card["id"],
                "date": card["day"].isoformat(),
                "start": card["time"],
                "home": {"name": card["home"]["name"], "logo": card["home"]["logo"]},
                "away": {"name": card["away"]["name"], "logo": card["away"]["logo"]},
                "league": card["league_label"],
                "arena_name": card["arena"],
            }
        )
    return out


async def get_ice_board(
    session: AsyncSession,
    *,
    city_id: int,
    day_from: date | None = None,
    days: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Лента «Поиск»: город, счётчики по дням, сеансы по времени и матчи в городе."""
    city = (
        await session.execute(text("SELECT id, name FROM cities WHERE id = :cid"), {"cid": int(city_id)})
    ).mappings().first()
    if city is None:
        raise CityNotFound(city_id)
    now = now or datetime.now(timezone.utc)
    tz_name = await _city_timezone(session, int(city_id))
    tz = _tz(tz_name)
    today = _local_today(tz_name, now)
    days = max(1, min(MAX_DAYS, int(days)))
    start = day_from or today
    end = start + timedelta(days=days - 1)

    rows = (
        await session.execute(
            _SESSIONS_SQL,
            {
                "cid": int(city_id),
                "day_from": start,
                "day_to": end,
                "now": now,
                "st": STATUS_ACTIVE,
                **public_scope_params(),
            },
        )
    ).mappings().all()

    counts = {start + timedelta(days=i): {"skate": 0, "hockey": 0, "figure": 0} for i in range(days)}
    thumbs = await _arena_thumbs(session, sorted({int(r["arena_id"]) for r in rows}))
    sessions: list[dict[str, Any]] = []
    for r in rows:
        group = KIND_GROUP[r["kind"]]
        day = r["local_date"]
        if day in counts:
            counts[day][group] += 1
        currency = r["currency_code"] or "BYN"
        sessions.append(
            {
                "session_id": int(r["session_id"]),
                "date": day.isoformat(),
                "start": _hhmm(r["starts_at_local"]),
                "end": _hhmm(r["ends_at_local"]),
                "group": group,
                "kind": r["kind"],
                "label": r["session_label"] or None,
                "age_note": r["age_note"] or None,
                "arena_id": int(r["arena_id"]),
                "arena_name": r["arena_name"],
                "district": r["district"] or None,
                "thumb": thumbs.get(int(r["arena_id"])),
                "price_adult": format_price_minor(r["price_adult_minor"], currency),
                "price_rental": format_price_minor(r["price_rental_minor"], currency),
            }
        )
    sessions.sort(key=lambda s: (s["date"], s["start"], s["arena_name"] or "", s["session_id"]))

    return {
        "city": {"id": int(city["id"]), "name": city["name"], "timezone": tz_name},
        "today": today.isoformat(),
        "now_local": now.astimezone(tz).strftime("%H:%M"),
        "days": [{"date": d.isoformat(), **c} for d, c in counts.items()],
        "sessions": sessions,
        "matches": await _matches(session, city_name=str(city["name"]), day_from=start, day_to=end, tz=tz),
    }
