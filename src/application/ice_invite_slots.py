"""Сеансы, на которые можно создать приглашение (TASK-234).

Список и ``create_invite`` делят ``INVITE_SESSION_PREDICATE``: будущий, активный,
вид из ``INVITE_KINDS``, арена видна публично. Отдельной копии правил здесь нет.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_invites import (
    INVITE_SESSION_PREDICATE,
    InviteRejected,
    _format_price,
    _local_parts,
    invite_session_params,
)
from src.shared.ice_discovery_scope import PUBLIC_ARENA_VISIBLE_SQL, PUBLIC_CITY_SCOPE_SQL, public_scope_params
from src.shared.notification_hours import NOTIFICATION_TZ

_HORIZON_DAYS = 14
_MINSK = ZoneInfo(NOTIFICATION_TZ)
_MINSK_DAY = f"(s.starts_at_utc AT TIME ZONE '{NOTIFICATION_TZ}')::date"

_CITY_SQL = f"""
SELECT c.id, c.name
FROM cities c
WHERE c.id = :city_id
  AND {PUBLIC_CITY_SCOPE_SQL}
"""

_LOCATE_SQL = f"""
SELECT a.city_id, s.starts_at_utc
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
WHERE s.id = :session_id
  AND ({PUBLIC_ARENA_VISIBLE_SQL})
"""

_FROM_INVITE_SESSIONS = f"""
FROM ice_sessions s
JOIN arenas a ON a.id = s.arena_id
LEFT JOIN arena_profiles p ON p.arena_id = a.id
JOIN cities c ON c.id = a.city_id
WHERE a.city_id = :city_id
  AND {INVITE_SESSION_PREDICATE}
"""

_SLOTS_SQL = f"""
SELECT
    s.id,
    s.kind,
    s.starts_at_utc,
    s.ends_at_utc,
    s.price_adult_minor,
    s.currency_code,
    a.id AS arena_id,
    a.name AS arena_name,
    a.address AS arena_address
{_FROM_INVITE_SESSIONS}
  AND {_MINSK_DAY} = :day
ORDER BY s.starts_at_utc, a.id, s.id
"""

_NEXT_DAY_SQL = f"""
SELECT {_MINSK_DAY} AS local_day
{_FROM_INVITE_SESSIONS}
  AND {_MINSK_DAY} > :day
  AND {_MINSK_DAY} <= :until
ORDER BY local_day
LIMIT 1
"""


async def list_invite_slots(
    session: AsyncSession,
    *,
    city_id: int | None,
    day: date | None,
    session_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Сеансы города на день по Минску. Пустой день — ``next_date`` в пределах 14 дней.

    ``session_id`` без города или даты (вход ``?s=``) подставляет город и день этого сеанса.
    """
    moment = now or datetime.now(timezone.utc)
    resolved_city = city_id
    resolved_day = day
    if resolved_city is None or resolved_day is None:
        if session_id is None:
            raise InviteRejected("Укажите город и дату.", 422)
        located = await _locate_session(session, session_id)
        if located is None:
            raise InviteRejected("session_id: сеанс не найден.", 404)
        if resolved_city is None:
            resolved_city = located[0]
        if resolved_day is None:
            resolved_day = located[1]
    city = await _visible_city(session, resolved_city)
    if city is None:
        raise InviteRejected("Город не найден.", 404)
    params = {
        "city_id": int(city["id"]),
        "day": resolved_day,
        **invite_session_params(now=moment),
    }
    rows = (await session.execute(text(_SLOTS_SQL), params)).mappings().all()
    arenas = _group_arenas(rows)
    next_date = None
    if not arenas:
        nxt = await _next_day(session, params, day=resolved_day)
        next_date = nxt.isoformat() if nxt is not None else None
    return {
        "date": resolved_day.isoformat(),
        "city_id": int(city["id"]),
        "city_name": str(city["name"]),
        "arenas": arenas,
        "next_date": next_date,
    }


async def _visible_city(session: AsyncSession, city_id: int) -> Mapping[str, Any] | None:
    if city_id <= 0:
        return None
    found = (
        (
            await session.execute(
                text(_CITY_SQL),
                {"city_id": int(city_id), **public_scope_params()},
            )
        )
        .mappings()
        .first()
    )
    if found is None:
        return None
    return {"id": int(found["id"]), "name": str(found["name"])}


async def _locate_session(session: AsyncSession, session_id: int) -> tuple[int, date] | None:
    if session_id <= 0:
        return None
    row = (
        (
            await session.execute(
                text(_LOCATE_SQL),
                {"session_id": int(session_id), **public_scope_params()},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return int(row["city_id"]), _minsk_day(row["starts_at_utc"])


async def _next_day(session: AsyncSession, params: Mapping[str, Any], *, day: date) -> date | None:
    found = (
        await session.execute(
            text(_NEXT_DAY_SQL),
            {**params, "until": day + timedelta(days=_HORIZON_DAYS)},
        )
    ).scalar_one_or_none()
    return _as_date(found)


def _group_arenas(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Катки в порядке ближайшего сеанса: строки уже отсортированы по началу."""
    arenas: dict[int, dict[str, Any]] = {}
    for row in rows:
        arena_id = int(row["arena_id"])
        bucket = arenas.get(arena_id)
        if bucket is None:
            address = str(row["arena_address"]).strip() if row["arena_address"] else ""
            bucket = {
                "id": arena_id,
                "name": row["arena_name"],
                "address": address or None,
                "sessions": [],
            }
            arenas[arena_id] = bucket
        parts = _local_parts(row["starts_at_utc"], row["ends_at_utc"])
        bucket["sessions"].append(
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "starts_at_local": parts["starts_at_local"],
                "ends_at_local": parts["ends_at_local"],
                "price": _format_price(row["price_adult_minor"], row["currency_code"]),
            }
        )
    return list(arenas.values())


def _minsk_day(value: datetime) -> date:
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(_MINSK).date()


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
