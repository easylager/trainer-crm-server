"""
Canonical ice session slots (TASK-050).

Manual admin entry and (later) parsers write the same columns after transform+validate.
Do not store a single "12 / 8 +6" price string. Client Ice tab will read only
``public_skate`` and ``open_ice``; other kinds are stored for admin completeness.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

DEFAULT_ARENA_TZ = "Europe/Minsk"
DURATION_MIN_MINUTES = 30
DURATION_MAX_MINUTES = 120
RECURRENCE_HORIZON_WEEKS = 4

KIND_PUBLIC_SKATE = "public_skate"
KIND_OPEN_ICE = "open_ice"
KIND_RENTAL = "rental"
KIND_SCHOOL_GROUP = "school_group"
KIND_EVENT = "event"
ICE_SESSION_KINDS = (
    KIND_PUBLIC_SKATE,
    KIND_OPEN_ICE,
    KIND_RENTAL,
    KIND_SCHOOL_GROUP,
    KIND_EVENT,
)
CLIENT_ICE_SESSION_KINDS = (KIND_PUBLIC_SKATE, KIND_OPEN_ICE)

STATUS_ACTIVE = "active"
STATUS_CANCELLED = "cancelled"
STATUS_SUPERSEDED = "superseded"
ICE_SESSION_STATUSES = (STATUS_ACTIVE, STATUS_CANCELLED, STATUS_SUPERSEDED)

SOURCE_ADMIN = "admin"
_UNSET = object()


class IceSessionValidationError(ValueError):
    """Reject a slot that fails the canonical validate gate."""


class IceSessionDurationError(IceSessionValidationError):
    """Duration must be 30–120 minutes."""


class IceSessionOverlapError(IceSessionValidationError):
    """Two active sessions on the same arena must not overlap."""


class IceSessionPriceError(IceSessionValidationError):
    """Prices are minor units and must be >= 0 when set."""


@dataclass(frozen=True)
class SessionDateTimes:
    starts_at_utc: datetime
    ends_at_utc: datetime
    local_date: date
    starts_at_local: time
    ends_at_local: time


def resolve_arena_timezone(tz_name: str | None) -> ZoneInfo:
    name = (tz_name or "").strip() or DEFAULT_ARENA_TZ
    return ZoneInfo(name)


def compute_session_datetimes(
    *,
    local_date: date,
    starts_at_local: time,
    duration_minutes: int,
    tz_name: str | None,
) -> SessionDateTimes:
    """Wall clock of the arena → UTC. ``local_date`` is always the start date (EDGE-001)."""
    tz = resolve_arena_timezone(tz_name)
    start_local = datetime.combine(local_date, starts_at_local, tzinfo=tz)
    end_local = start_local + timedelta(minutes=int(duration_minutes))
    return SessionDateTimes(
        starts_at_utc=start_local.astimezone(timezone.utc),
        ends_at_utc=end_local.astimezone(timezone.utc),
        local_date=local_date,
        starts_at_local=starts_at_local,
        ends_at_local=end_local.timetz().replace(tzinfo=None),
    )


def duration_minutes(starts_at_utc: datetime, ends_at_utc: datetime) -> int:
    return int((ends_at_utc - starts_at_utc).total_seconds() // 60)


def validate_duration_minutes(minutes: int) -> int:
    value = int(minutes)
    if value < DURATION_MIN_MINUTES or value > DURATION_MAX_MINUTES:
        raise IceSessionDurationError(
            f"Длительность сеанса должна быть от {DURATION_MIN_MINUTES} до {DURATION_MAX_MINUTES} минут"
        )
    return value


def validate_kind(kind: str) -> str:
    value = (kind or "").strip()
    if value not in ICE_SESSION_KINDS:
        raise IceSessionValidationError(
            "Тип сеанса: public_skate, open_ice, rental, school_group или event"
        )
    return value


def validate_prices(
    *,
    price_adult_minor: int | None,
    price_child_minor: int | None,
    price_rental_minor: int | None,
) -> None:
    for value in (price_adult_minor, price_child_minor, price_rental_minor):
        if value is not None and int(value) < 0:
            raise IceSessionPriceError("Цена не может быть отрицательной")


def compute_price_minor(
    price_adult_minor: int | None,
    price_child_minor: int | None,
    price_rental_minor: int | None = None,
) -> int | None:
    """Sort/filter key: min of adult/child. Rental is never the sort key (EDGE-003)."""
    del price_rental_minor
    candidates = [int(v) for v in (price_adult_minor, price_child_minor) if v is not None]
    if not candidates:
        return None
    return min(candidates)


def totals_by_currency(sessions: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Sum ``price_minor`` inside each currency. Never mix BYN and RUB into one total (AC-004)."""
    totals: dict[str, int] = {}
    for row in sessions:
        code = str(row["currency_code"])
        amount = int(row.get("price_minor") or 0)
        totals[code] = totals.get(code, 0) + amount
    return totals


def intervals_overlap(
    a_start: datetime,
    a_end: datetime,
    b_start: datetime,
    b_end: datetime,
) -> bool:
    return a_start < b_end and b_start < a_end


def validate_no_overlap(
    existing: Sequence[Mapping[str, Any]],
    *,
    starts_at_utc: datetime,
    ends_at_utc: datetime,
    ignore_session_id: int | None = None,
) -> None:
    for row in existing:
        if ignore_session_id is not None and int(row.get("id") or 0) == int(ignore_session_id):
            continue
        if (row.get("status") or STATUS_ACTIVE) != STATUS_ACTIVE:
            continue
        if intervals_overlap(
            starts_at_utc,
            ends_at_utc,
            row["starts_at_utc"],
            row["ends_at_utc"],
        ):
            raise IceSessionOverlapError("Сеанс пересекается с другим сеансом на этой арене")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def parse_hhmm(value: str | time) -> time:
    if isinstance(value, time):
        return time(value.hour, value.minute)
    raw = (value or "").strip()
    parts = raw.split(":")
    if len(parts) < 2:
        raise IceSessionValidationError("Время начала в формате ЧЧ:ММ")
    try:
        return time(int(parts[0]), int(parts[1]))
    except ValueError as exc:
        raise IceSessionValidationError("Время начала в формате ЧЧ:ММ") from exc


def format_hhmm(value: time | datetime | str) -> str:
    if isinstance(value, str):
        parsed = parse_hhmm(value)
        return f"{parsed.hour:02d}:{parsed.minute:02d}"
    if isinstance(value, datetime):
        return f"{value.hour:02d}:{value.minute:02d}"
    return f"{value.hour:02d}:{value.minute:02d}"


def weekly_occurrence_dates(start: date, weeks: int = RECURRENCE_HORIZON_WEEKS) -> list[date]:
    return [start + timedelta(weeks=i) for i in range(int(weeks))]


def next_weekday_on_or_after(start: date, weekday: int) -> date:
    delta = (int(weekday) - start.weekday()) % 7
    return start + timedelta(days=delta)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def serialize_ice_session(row: Mapping[str, Any]) -> dict[str, Any]:
    starts_utc = _as_utc(row["starts_at_utc"])
    ends_utc = _as_utc(row["ends_at_utc"])
    local_date = row["local_date"]
    if isinstance(local_date, datetime):
        local_date = local_date.date()
    return {
        "id": int(row["id"]),
        "arena_id": int(row["arena_id"]),
        "kind": row["kind"],
        "status": row["status"],
        "starts_at_utc": starts_utc.isoformat(),
        "ends_at_utc": ends_utc.isoformat(),
        "local_date": local_date.isoformat() if hasattr(local_date, "isoformat") else str(local_date),
        "starts_at_local": format_hhmm(row["starts_at_local"]),
        "ends_at_local": format_hhmm(row["ends_at_local"]),
        "price_adult_minor": row["price_adult_minor"],
        "price_child_minor": row["price_child_minor"],
        "price_rental_minor": row["price_rental_minor"],
        "price_minor": row["price_minor"],
        "currency_code": row["currency_code"],
        "price_note": row["price_note"],
        "session_label": row.get("session_label"),
        "age_note": row.get("age_note"),
        "capacity_note": row.get("capacity_note"),
        "external_url": row.get("external_url"),
        "recurrence_key": row.get("recurrence_key"),
        "source_id": row.get("source_id"),
        "observed_at": _as_utc(row["observed_at"]).isoformat() if row.get("observed_at") else None,
        "valid_until": _as_utc(row["valid_until"]).isoformat() if row.get("valid_until") else None,
        "confidence": row.get("confidence"),
    }


_SESSION_COLUMNS = """
    id, arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local, ends_at_local,
    price_adult_minor, price_child_minor, price_rental_minor, price_minor, currency_code,
    price_note, session_label, age_note, capacity_note, external_url, status, recurrence_key,
    source_id, observed_at, valid_until, confidence
"""


def _row_to_mapping(row: Any) -> dict[str, Any]:
    keys = [
        "id",
        "arena_id",
        "kind",
        "starts_at_utc",
        "ends_at_utc",
        "local_date",
        "starts_at_local",
        "ends_at_local",
        "price_adult_minor",
        "price_child_minor",
        "price_rental_minor",
        "price_minor",
        "currency_code",
        "price_note",
        "session_label",
        "age_note",
        "capacity_note",
        "external_url",
        "status",
        "recurrence_key",
        "source_id",
        "observed_at",
        "valid_until",
        "confidence",
    ]
    return dict(zip(keys, row, strict=True))


async def _arena_context(session: AsyncSession, arena_id: int) -> tuple[int, str]:
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text(
            """
            SELECT a.city_id, p.timezone
            FROM arenas a
            LEFT JOIN arena_profiles p ON p.arena_id = a.id
            WHERE a.id = :id
            """
        ),
        {"id": arena_id},
    )
    row = result.fetchone()
    if not row:
        raise LookupError("arena not found")
    tz_name = (row[1] or "").strip() or DEFAULT_ARENA_TZ
    return int(row[0]), tz_name


async def _load_active_sessions(session: AsyncSession, arena_id: int) -> list[dict[str, Any]]:
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text(
            f"SELECT {_SESSION_COLUMNS} FROM ice_sessions WHERE arena_id = :aid"
        ),
        {"aid": arena_id},
    )
    return [_row_to_mapping(r) for r in result.fetchall()]


async def _insert_session(
    session: AsyncSession,
    *,
    arena_id: int,
    kind: str,
    parts: SessionDateTimes,
    price_adult_minor: int | None,
    price_child_minor: int | None,
    price_rental_minor: int | None,
    currency_code: str,
    price_note: str | None,
    session_label: str | None,
    age_note: str | None,
    capacity_note: str | None,
    external_url: str | None,
    status: str,
    recurrence_key: str | None,
    source_id: str | None,
    observed_at: datetime,
    confidence: float | None,
) -> dict[str, Any]:
    from sqlalchemy import text as sql_text

    price_minor = compute_price_minor(price_adult_minor, price_child_minor, price_rental_minor)
    result = await session.execute(
        sql_text(
            f"""
            INSERT INTO ice_sessions (
                arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local, ends_at_local,
                price_adult_minor, price_child_minor, price_rental_minor, price_minor, currency_code,
                price_note, session_label, age_note, capacity_note, external_url, status, recurrence_key,
                source_id, observed_at, confidence
            ) VALUES (
                :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date, :starts_at_local, :ends_at_local,
                :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor, :currency_code,
                :price_note, :session_label, :age_note, :capacity_note, :external_url, :status, :recurrence_key,
                :source_id, :observed_at, :confidence
            )
            RETURNING {_SESSION_COLUMNS}
            """
        ),
        {
            "arena_id": arena_id,
            "kind": kind,
            "starts_at_utc": parts.starts_at_utc,
            "ends_at_utc": parts.ends_at_utc,
            "local_date": parts.local_date,
            "starts_at_local": parts.starts_at_local,
            "ends_at_local": parts.ends_at_local,
            "price_adult_minor": price_adult_minor,
            "price_child_minor": price_child_minor,
            "price_rental_minor": price_rental_minor,
            "price_minor": price_minor,
            "currency_code": currency_code,
            "price_note": price_note,
            "session_label": session_label,
            "age_note": age_note,
            "capacity_note": capacity_note,
            "external_url": external_url,
            "status": status,
            "recurrence_key": recurrence_key,
            "source_id": source_id,
            "observed_at": observed_at,
            "confidence": confidence,
        },
    )
    return _row_to_mapping(result.fetchone())


async def create_ice_session(
    session: AsyncSession,
    arena_id: int,
    *,
    local_date: date,
    starts_at_local: str | time,
    duration_minutes: int,
    kind: str = KIND_PUBLIC_SKATE,
    price_adult_minor: int | None = None,
    price_child_minor: int | None = None,
    price_rental_minor: int | None = None,
    price_note: str | None = None,
    session_label: str | None = None,
    age_note: str | None = None,
    capacity_note: str | None = None,
    external_url: str | None = None,
    repeat_weekly: bool = False,
    horizon_weeks: int = RECURRENCE_HORIZON_WEEKS,
) -> dict[str, Any]:
    from src.shared.currency import resolve_currency

    kind_value = validate_kind(kind)
    minutes = validate_duration_minutes(duration_minutes)
    validate_prices(
        price_adult_minor=price_adult_minor,
        price_child_minor=price_child_minor,
        price_rental_minor=price_rental_minor,
    )
    city_id, tz_name = await _arena_context(session, arena_id)
    currency_code = await resolve_currency(session, city_id)
    start_time = parse_hhmm(starts_at_local)
    dates = weekly_occurrence_dates(local_date, horizon_weeks) if repeat_weekly else [local_date]
    existing = await _load_active_sessions(session, arena_id)
    planned: list[SessionDateTimes] = []
    for occ in dates:
        parts = compute_session_datetimes(
            local_date=occ,
            starts_at_local=start_time,
            duration_minutes=minutes,
            tz_name=tz_name,
        )
        validate_no_overlap(existing, starts_at_utc=parts.starts_at_utc, ends_at_utc=parts.ends_at_utc)
        for prev in planned:
            if intervals_overlap(parts.starts_at_utc, parts.ends_at_utc, prev.starts_at_utc, prev.ends_at_utc):
                raise IceSessionOverlapError("Сеанс пересекается с другим сеансом на этой арене")
        planned.append(parts)

    recurrence_key = str(uuid.uuid4()) if repeat_weekly else None
    now = datetime.now(timezone.utc)
    inserted: list[dict[str, Any]] = []
    for parts in planned:
        row = await _insert_session(
            session,
            arena_id=arena_id,
            kind=kind_value,
            parts=parts,
            price_adult_minor=price_adult_minor,
            price_child_minor=price_child_minor,
            price_rental_minor=price_rental_minor,
            currency_code=currency_code,
            price_note=price_note,
            session_label=session_label,
            age_note=age_note,
            capacity_note=capacity_note,
            external_url=external_url,
            status=STATUS_ACTIVE,
            recurrence_key=recurrence_key,
            source_id=SOURCE_ADMIN,
            observed_at=now,
            confidence=1.0,
        )
        inserted.append(row)
        existing.append(row)
    return serialize_ice_session(inserted[0])


async def list_ice_week_grid(
    session: AsyncSession,
    arena_id: int,
    *,
    week_start: date,
    include_cancelled: bool = False,
) -> dict[str, Any]:
    from sqlalchemy import text as sql_text
    from src.shared.currency import resolve_currency

    city_id, tz_name = await _arena_context(session, arena_id)
    currency_code = await resolve_currency(session, city_id)
    monday = monday_of(week_start)
    sunday = monday + timedelta(days=6)
    result = await session.execute(
        sql_text(
            f"""
            SELECT {_SESSION_COLUMNS}
            FROM ice_sessions
            WHERE arena_id = :aid
              AND local_date >= :start
              AND local_date <= :end
              AND (:include_cancelled OR status = :active)
            ORDER BY local_date, starts_at_local, id
            """
        ),
        {
            "aid": arena_id,
            "start": monday,
            "end": sunday,
            "include_cancelled": include_cancelled,
            "active": STATUS_ACTIVE,
        },
    )
    by_date: dict[str, list[dict[str, Any]]] = {}
    for raw in result.fetchall():
        item = serialize_ice_session(_row_to_mapping(raw))
        by_date.setdefault(item["local_date"], []).append(item)
    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        key = day.isoformat()
        days.append(
            {
                "local_date": key,
                "weekday": day.weekday(),
                "sessions": by_date.get(key, []),
            }
        )
    return {
        "week_start": monday.isoformat(),
        "timezone": tz_name,
        "currency_code": currency_code,
        "days": days,
    }


async def update_ice_session(
    session: AsyncSession,
    session_id: int,
    *,
    local_date: date | None = None,
    starts_at_local: str | time | None = None,
    duration_minutes: int | None = None,
    kind: str | None = None,
    price_adult_minor: Any = _UNSET,
    price_child_minor: Any = _UNSET,
    price_rental_minor: Any = _UNSET,
    price_note: Any = _UNSET,
    session_label: Any = _UNSET,
    age_note: Any = _UNSET,
    capacity_note: Any = _UNSET,
    external_url: Any = _UNSET,
) -> dict[str, Any]:
    result = await session.execute(
        sql_text(f"SELECT {_SESSION_COLUMNS} FROM ice_sessions WHERE id = :id"),
        {"id": session_id},
    )
    raw = result.fetchone()
    if not raw:
        raise LookupError("session not found")
    current = _row_to_mapping(raw)
    kind_value = validate_kind(kind) if kind is not None else current["kind"]
    day = local_date or current["local_date"]
    start_time = parse_hhmm(starts_at_local) if starts_at_local is not None else parse_hhmm(current["starts_at_local"])
    minutes = (
        validate_duration_minutes(duration_minutes)
        if duration_minutes is not None
        else duration_minutes_span(current["starts_at_utc"], current["ends_at_utc"])
    )
    adult = current["price_adult_minor"] if price_adult_minor is _UNSET else price_adult_minor
    child = current["price_child_minor"] if price_child_minor is _UNSET else price_child_minor
    rental = current["price_rental_minor"] if price_rental_minor is _UNSET else price_rental_minor
    validate_prices(price_adult_minor=adult, price_child_minor=child, price_rental_minor=rental)
    _city_id, tz_name = await _arena_context(session, int(current["arena_id"]))
    parts = compute_session_datetimes(
        local_date=day,
        starts_at_local=start_time,
        duration_minutes=minutes,
        tz_name=tz_name,
    )
    existing = await _load_active_sessions(session, int(current["arena_id"]))
    validate_no_overlap(
        existing,
        starts_at_utc=parts.starts_at_utc,
        ends_at_utc=parts.ends_at_utc,
        ignore_session_id=session_id,
    )
    note = current["price_note"] if price_note is _UNSET else price_note
    label = current["session_label"] if session_label is _UNSET else session_label
    age = current["age_note"] if age_note is _UNSET else age_note
    cap = current["capacity_note"] if capacity_note is _UNSET else capacity_note
    url = current["external_url"] if external_url is _UNSET else external_url
    price_minor = compute_price_minor(adult, child, rental)
    updated = await session.execute(
        sql_text(
            f"""
            UPDATE ice_sessions SET
                kind = :kind,
                starts_at_utc = :starts_at_utc,
                ends_at_utc = :ends_at_utc,
                local_date = :local_date,
                starts_at_local = :starts_at_local,
                ends_at_local = :ends_at_local,
                price_adult_minor = :price_adult_minor,
                price_child_minor = :price_child_minor,
                price_rental_minor = :price_rental_minor,
                price_minor = :price_minor,
                price_note = :price_note,
                session_label = :session_label,
                age_note = :age_note,
                capacity_note = :capacity_note,
                external_url = :external_url
            WHERE id = :id
            RETURNING {_SESSION_COLUMNS}
            """
        ),
        {
            "id": session_id,
            "kind": kind_value,
            "starts_at_utc": parts.starts_at_utc,
            "ends_at_utc": parts.ends_at_utc,
            "local_date": parts.local_date,
            "starts_at_local": parts.starts_at_local,
            "ends_at_local": parts.ends_at_local,
            "price_adult_minor": adult,
            "price_child_minor": child,
            "price_rental_minor": rental,
            "price_minor": price_minor,
            "price_note": note,
            "session_label": label,
            "age_note": age,
            "capacity_note": cap,
            "external_url": url,
        },
    )
    return serialize_ice_session(_row_to_mapping(updated.fetchone()))


def duration_minutes_span(starts_at_utc: datetime, ends_at_utc: datetime) -> int:
    return duration_minutes(_as_utc(starts_at_utc), _as_utc(ends_at_utc))


async def apply_ice_session_patch(
    session: AsyncSession,
    session_id: int,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if "local_date" in fields:
        kwargs["local_date"] = fields["local_date"]
    if "starts_at_local" in fields:
        kwargs["starts_at_local"] = fields["starts_at_local"]
    if "duration_minutes" in fields:
        kwargs["duration_minutes"] = fields["duration_minutes"]
    if "kind" in fields:
        kwargs["kind"] = fields["kind"]
    for key in (
        "price_adult_minor",
        "price_child_minor",
        "price_rental_minor",
        "price_note",
        "session_label",
        "age_note",
        "capacity_note",
        "external_url",
    ):
        if key in fields:
            kwargs[key] = fields[key]
        else:
            kwargs[key] = _UNSET
    return await update_ice_session(session, session_id, **kwargs)


async def delete_ice_session(session: AsyncSession, session_id: int) -> dict[str, Any]:
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text(f"SELECT {_SESSION_COLUMNS} FROM ice_sessions WHERE id = :id"),
        {"id": session_id},
    )
    raw = result.fetchone()
    if not raw:
        raise LookupError("session not found")
    current = _row_to_mapping(raw)
    if current.get("recurrence_key"):
        updated = await session.execute(
            sql_text(
                f"""
                UPDATE ice_sessions SET status = :st
                WHERE id = :id
                RETURNING {_SESSION_COLUMNS}
                """
            ),
            {"st": STATUS_CANCELLED, "id": session_id},
        )
        return serialize_ice_session(_row_to_mapping(updated.fetchone()))
    await session.execute(sql_text("DELETE FROM ice_sessions WHERE id = :id"), {"id": session_id})
    return {"ok": True, "deleted": True, "id": session_id}


async def copy_ice_week(
    session: AsyncSession,
    arena_id: int,
    *,
    from_week_start: date,
) -> dict[str, Any]:
    grid = await list_ice_week_grid(session, arena_id, week_start=from_week_start)
    copied = 0
    skipped = 0
    for day in grid["days"]:
        for slot in day["sessions"]:
            if slot["status"] != STATUS_ACTIVE:
                continue
            target = date.fromisoformat(slot["local_date"]) + timedelta(days=7)
            minutes = duration_minutes(
                datetime.fromisoformat(slot["starts_at_utc"]),
                datetime.fromisoformat(slot["ends_at_utc"]),
            )
            try:
                await create_ice_session(
                    session,
                    arena_id,
                    local_date=target,
                    starts_at_local=slot["starts_at_local"],
                    duration_minutes=minutes,
                    kind=slot["kind"],
                    price_adult_minor=slot["price_adult_minor"],
                    price_child_minor=slot["price_child_minor"],
                    price_rental_minor=slot["price_rental_minor"],
                    price_note=slot["price_note"],
                    session_label=slot["session_label"],
                    age_note=slot["age_note"],
                    capacity_note=slot["capacity_note"],
                    external_url=slot["external_url"],
                    repeat_weekly=False,
                )
                copied += 1
            except IceSessionOverlapError:
                skipped += 1
    return {"copied": copied, "skipped": skipped}


async def rematerialize_recurrence(
    session: AsyncSession,
    recurrence_key: str,
    *,
    from_date: date | None = None,
    horizon_weeks: int = RECURRENCE_HORIZON_WEEKS,
) -> dict[str, Any]:
    from sqlalchemy import text as sql_text

    result = await session.execute(
        sql_text(
            f"""
            SELECT {_SESSION_COLUMNS}
            FROM ice_sessions
            WHERE recurrence_key = :key
            ORDER BY local_date, id
            LIMIT 1
            """
        ),
        {"key": recurrence_key},
    )
    raw = result.fetchone()
    if not raw:
        raise LookupError("recurrence not found")
    template = _row_to_mapping(raw)
    _city_id, tz_name = await _arena_context(session, int(template["arena_id"]))
    today = from_date or datetime.now(resolve_arena_timezone(tz_name)).date()
    template_day = template["local_date"]
    if isinstance(template_day, datetime):
        template_day = template_day.date()
    first = next_weekday_on_or_after(today, template_day.weekday())
    minutes = duration_minutes_span(template["starts_at_utc"], template["ends_at_utc"])
    existing = await _load_active_sessions(session, int(template["arena_id"]))
    created = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    for occ in weekly_occurrence_dates(first, horizon_weeks):
        parts = compute_session_datetimes(
            local_date=occ,
            starts_at_local=parse_hhmm(template["starts_at_local"]),
            duration_minutes=minutes,
            tz_name=tz_name,
        )
        already = any(
            row.get("recurrence_key") == recurrence_key and row["local_date"] == occ
            for row in existing
        )
        if already:
            skipped += 1
            continue
        try:
            validate_no_overlap(existing, starts_at_utc=parts.starts_at_utc, ends_at_utc=parts.ends_at_utc)
        except IceSessionOverlapError:
            skipped += 1
            continue
        inserted = await session.execute(
            sql_text(
                f"""
                INSERT INTO ice_sessions (
                    arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local, ends_at_local,
                    price_adult_minor, price_child_minor, price_rental_minor, price_minor, currency_code,
                    price_note, session_label, age_note, capacity_note, external_url, status, recurrence_key,
                    source_id, observed_at, confidence
                ) VALUES (
                    :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date, :starts_at_local, :ends_at_local,
                    :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor, :currency_code,
                    :price_note, :session_label, :age_note, :capacity_note, :external_url, :status, :recurrence_key,
                    :source_id, :observed_at, :confidence
                )
                ON CONFLICT (recurrence_key, local_date) WHERE recurrence_key IS NOT NULL
                DO NOTHING
                RETURNING {_SESSION_COLUMNS}
                """
            ),
            {
                "arena_id": template["arena_id"],
                "kind": template["kind"],
                "starts_at_utc": parts.starts_at_utc,
                "ends_at_utc": parts.ends_at_utc,
                "local_date": parts.local_date,
                "starts_at_local": parts.starts_at_local,
                "ends_at_local": parts.ends_at_local,
                "price_adult_minor": template["price_adult_minor"],
                "price_child_minor": template["price_child_minor"],
                "price_rental_minor": template["price_rental_minor"],
                "price_minor": template["price_minor"],
                "currency_code": template["currency_code"],
                "price_note": template["price_note"],
                "session_label": template["session_label"],
                "age_note": template["age_note"],
                "capacity_note": template["capacity_note"],
                "external_url": template["external_url"],
                "status": STATUS_ACTIVE,
                "recurrence_key": recurrence_key,
                "source_id": SOURCE_ADMIN,
                "observed_at": now,
                "confidence": 1.0,
            },
        )
        row = inserted.fetchone()
        if row:
            existing.append(_row_to_mapping(row))
            created += 1
        else:
            skipped += 1
    return {"created": created, "skipped": skipped, "recurrence_key": recurrence_key}

