"""TASK-447 (этап 2 редизайна): доп. ключи ``home.*`` в бутстрапе главной.

Только под флагом ``redesign_s2``: правила городов (один каток / маленький город),
«На неделе», «следующий лёд», соседние катки и профиль/игрок для верхнего состояния.
Чистые билдеры покрыты тестами; сборка — один запрос на 60 дней.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.city_style_b import VARIANT_ONE
from src.application.hub_home import _photo, _place_href
from src.application.ice_city_day import format_price_minor
from src.shared.public_display import format_clock

logger = logging.getLogger(__name__)

# «Маленький город» для «На неделе»: VARIANT_ONE или мало сеансов на 7 дней вперёд.
SMALL_WEEK_MAX_SESSIONS = 40

_NEXT_ICE_HORIZON_DAYS = 60
_WEEK_DAYS = 7
_DAY_TIMES_MAX = 6
_NEARBY_MAX = 6

_WEEKDAYS_CAP = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

def _local_date(row: Mapping[str, Any]) -> date | None:
    raw = row.get("local_date")
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw or ""))
    except ValueError:
        return None


def _start_utc(row: Mapping[str, Any]) -> datetime | None:
    raw = row.get("starts_at_utc")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    return None


def _day_label(day: date, today: date) -> str:
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return _WEEKDAYS_CAP[day.weekday()]


def _day_label_long(day: date, today: date) -> str:
    """«Сегодня» / «Завтра» / «сб, 28» — для next_ice и one_rink."""
    if day == today:
        return "Сегодня"
    if day == today + timedelta(days=1):
        return "Завтра"
    return f"{_WEEKDAYS_CAP[day.weekday()].lower()}, {day.day}"


def is_small_city(variant: str | None, week_session_count: int) -> bool:
    """«На неделе» показываем только маленьким городам: один каток или мало льда."""
    return variant == VARIANT_ONE or int(week_session_count) <= SMALL_WEEK_MAX_SESSIONS


def build_week(
    rows: Sequence[Mapping[str, Any]],
    places: Sequence[Mapping[str, Any]],
    *,
    today: date,
    now: datetime,
) -> list[dict[str, Any]]:
    """7 дней от сегодня: чипы времени по дням (≤6), прошедшие сегодняшние — ``past``.

    ``arena_name`` у чипа только когда в городе больше одного катка.
    """
    rinks = [p for p in places or [] if str(p.get("venue_type") or "ice") in ("ice", "outdoor")]
    multi = len(rinks) > 1
    by_slug = {str(p.get("slug") or ""): p for p in rinks}
    by_day: dict[date, list[Mapping[str, Any]]] = {}
    for row in rows or []:
        d = _local_date(row)
        if d is None or d < today or d >= today + timedelta(days=_WEEK_DAYS):
            continue
        by_day.setdefault(d, []).append(row)
    out: list[dict[str, Any]] = []
    for i in range(_WEEK_DAYS):
        day = today + timedelta(days=i)
        times: list[dict[str, Any]] = []
        for row in sorted(by_day.get(day) or [], key=lambda r: str(r.get("starts_at_local") or ""))[:_DAY_TIMES_MAX]:
            place = by_slug.get(str(row.get("arena_slug") or "").strip()) or {}
            arena_id = place.get("id")
            start_utc = _start_utc(row)
            chip = {
                "time": format_clock(str(row.get("starts_at_local") or "")),
                "end": format_clock(str(row.get("ends_at_local") or "")),
                "session_id": row.get("session_id"),
                "arena_id": int(arena_id) if arena_id is not None else None,
                "href": _place_href(arena_id, row.get("session_id")),
                "past": bool(start_utc and start_utc <= now),
            }
            if multi:
                chip["arena_name"] = str(row.get("arena_name") or "")
            times.append(chip)
        out.append({"date": day.isoformat(), "label": _day_label(day, today), "sub": str(day.day), "times": times})
    return out


def build_next_ice(
    rows: Sequence[Mapping[str, Any]],
    places: Sequence[Mapping[str, Any]],
    *,
    today: date,
    now: datetime,
) -> dict[str, Any] | None:
    """Первый будущий сеанс из уже выбранных строк горизонта (``None`` — межсезонье)."""
    by_slug = {str(p.get("slug") or ""): p for p in places or []}
    for row in rows or []:
        start_utc = _start_utc(row)
        if start_utc is None or start_utc <= now:
            continue
        day = _local_date(row) or start_utc.date()
        place = by_slug.get(str(row.get("arena_slug") or "").strip()) or {}
        arena_id = place.get("id")
        return {
            "date_label": _day_label_long(day, today),
            "date_sub": f"{_WEEKDAYS_CAP[day.weekday()].lower()} {day.day}",
            "time": format_clock(str(row.get("starts_at_local") or "")),
            "arena_id": int(arena_id) if arena_id is not None else None,
            "arena_name": str(row.get("arena_name") or ""),
            "photo": _photo(place).get("card") or _photo(place).get("thumb"),
            "href": _place_href(arena_id, row.get("session_id")),
        }
    return None


def build_one_rink(
    rows: Sequence[Mapping[str, Any]],
    places: Sequence[Mapping[str, Any]],
    *,
    today: date,
    now: datetime,
    invite_link: Any = None,
) -> dict[str, Any] | None:
    """Белый билет ближайшего сеанса единственного катка (макет «Пинск»)."""
    future = [r for r in rows or [] if (_start_utc(r) or datetime.min.replace(tzinfo=timezone.utc)) > now]
    future.sort(key=lambda r: _start_utc(r))
    if not future:
        return None
    row = future[0]
    day = _local_date(row)
    if day is None or day >= today + timedelta(days=_WEEK_DAYS):
        return None
    place = next((p for p in places or [] if str(p.get("slug") or "") == str(row.get("arena_slug") or "").strip()), {})
    arena_id = place.get("id")
    later = next(
        (r for r in future[1:] if _local_date(r) == day),
        None,
    )
    currency = str(row.get("currency_code") or "BYN")
    prices: list[dict[str, str]] = []
    adult = row.get("price_adult_minor")
    rental = row.get("price_rental_minor")
    if adult is not None:
        prices.append({"value": format_price_minor(int(adult), currency), "label": "взрослый"})
    if adult is not None and rental is not None:
        prices.append({"value": format_price_minor(int(adult) + int(rental), currency), "label": "с прокатом"})
    start_utc = _start_utc(row)
    return {
        "time": format_clock(str(row.get("starts_at_local") or "")),
        "end": format_clock(str(row.get("ends_at_local") or "")),
        "minutes_until": int((start_utc - now).total_seconds() // 60) if start_utc else None,
        "day_label": _day_label(day, today),
        "title": str(row.get("basis_label") or "Массовое катание"),
        "arena_id": int(arena_id) if arena_id is not None else None,
        "arena_name": str(row.get("arena_name") or ""),
        "later_today": format_clock(str(later.get("starts_at_local") or "")) if later else None,
        "prices": prices,
        "href": _place_href(arena_id, row.get("session_id")),
        "session_id": row.get("session_id"),
        "invite_url": invite_link(int(arena_id), row.get("session_id"))
        if invite_link and arena_id is not None
        else None,
        "map_link": place.get("yandex_url") or None,
    }


def build_nearby(nearby: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """«Лёд рядом»: соседние города с сеансом — карточки рейла (≤6)."""
    out: list[dict[str, Any]] = []
    for item in (nearby or [])[:_NEARBY_MAX]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        when = {"today": "сегодня", "tomorrow": "завтра"}.get(str(item.get("when") or ""), "")
        sub_bits = [b for b in (when, format_clock(str(item.get("time") or "")) if item.get("time") else "", item.get("distance") or "") if b]
        out.append(
            {
                "name": name,
                "photo": item.get("photo_url"),
                "sub": " · ".join(sub_bits),
                "rink_count": int(item.get("rink_count") or 0),
                "href": item.get("href") or None,
            }
        )
    return out


async def load_profile_s2(
    session: AsyncSession,
    *,
    telegram_id: int,
    requested_profile_id: int | None,
) -> dict[str, Any]:
    """``home.profile`` + ``home.kk_player``: действующий профиль и игрок «Кто кого»."""
    from src.application.client_profile_use_cases import resolve_acting_client_id

    acting = await resolve_acting_client_id(session, int(telegram_id), requested_profile_id)
    profile: dict[str, Any] | None = None
    if acting is not None:
        row = (
            await session.execute(
                text("SELECT id, first_name, telegram_id FROM clients WHERE id = :id"),
                {"id": int(acting)},
            )
        ).mappings().first()
        if row is not None:
            profile = {
                "id": int(row["id"]),
                "name": str(row.get("first_name") or "").strip(),
                "is_own": int(row.get("telegram_id") or 0) == int(telegram_id),
            }
    kk = (
        await session.execute(
            text("SELECT 1 FROM hockey_players WHERE player_key = :k LIMIT 1"),
            {"k": int(telegram_id)},
        )
    ).first()
    return {"profile": profile, "kk_player": kk is not None}


async def load_home_s2(
    session: AsyncSession,
    *,
    view: Mapping[str, Any],
    city_id: int,
    now: datetime,
    invite_link: Any = None,
) -> dict[str, Any]:
    """Ключи ``home.*`` этапа 2 по уже собранному ``load_city_hub_view``.

    Один запрос сеансов на 60 дней: из него — неделя (маленький город),
    «следующий лёд» и билет единственного катка. Соседние катки — из ``view``.
    """
    from src.application.catalog_home_page import _USER_UPCOMING_SQL, _session_card
    from src.application.ice_session_use_cases import STATUS_ACTIVE
    from src.shared.ice_discovery_scope import public_scope_params

    variant = str(view.get("variant") or "")
    today = view.get("today")
    today = today if isinstance(today, date) else now.astimezone(ZoneInfo("Europe/Minsk")).date()
    places = [
        p for p in view.get("places") or []
        if str(p.get("venue_type") or "ice") in ("ice", "outdoor")
    ]
    rows = (
        (
            await session.execute(
                _USER_UPCOMING_SQL,
                {
                    "user_city_id": int(city_id),
                    "starts_at": now,
                    "ends_at": now + timedelta(days=_NEXT_ICE_HORIZON_DAYS),
                    "now": now,
                    "st": STATUS_ACTIVE,
                    "lim": 200,
                    **public_scope_params(),
                },
            )
        )
        .mappings()
        .all()
    )
    cards = [_session_card(r, now=now) for r in rows]
    week_rows = [c for c in cards if (d := _local_date(c)) is not None and today <= d < today + timedelta(days=_WEEK_DAYS)]

    out: dict[str, Any] = {"variant": variant}
    if is_small_city(variant, len(week_rows)):
        out["week"] = build_week(week_rows, places, today=today, now=now)

    today_left = any(
        _local_date(c) == today and (_start_utc(c) or now) > now for c in cards
    )
    if not today_left:
        # Ключ есть всегда, когда сегодня стартующих сеансов не осталось:
        # None = межсезонье (в 60 днях ничего нет).
        out["next_ice"] = build_next_ice(cards, places, today=today, now=now)

    if variant == VARIANT_ONE:
        one = build_one_rink(week_rows, places, today=today, now=now, invite_link=invite_link)
        if one is not None:
            out["one_rink"] = one
        nearby = build_nearby(view.get("nearby") or [])
        if nearby:
            out["nearby"] = nearby
    return out
