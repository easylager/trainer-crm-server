"""Admin «Источники расписаний»: where each Belarusian rink's schedule comes from.

The admin records the source link, how we collect it (server / own computer with a Belarusian
IP / manual check / none) and the weekdays the rink usually posts. Without a row the mode is
derived from ``ice_parser_jobs``, so the list is useful before anyone has edited anything.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.place_links import place_page_url, place_start_param, telegram_bot_start_link
from src.shared.config import Settings

FETCH_MODES = ("server", "byip", "manual", "none")
BROKEN_STREAK = 3
STALE_AFTER = timedelta(days=7)  # без новых слотов дольше — алерт «N дней без слотов»
# Скрыты из админки источников: Замок (парсер стабилен, раскупают за час), Минск Арена и Олимпик-арена.
HIDDEN_ARENA_IDS = (2, 3, 9)
LOG_SOURCES = ("parser", "manual", "screenshot", "script")
LOG_MAX_DAYS = 31
LOG_MAX_EVENTS = 3000
_MINSK = ZoneInfo("Europe/Minsk")

_HOST_KINDS: tuple[tuple[str, str], ...] = (
    ("instagram.com", "instagram"),
    ("vk.com", "vk"),
    ("vk.ru", "vk"),
    ("t.me", "telegram"),
    ("telegram.me", "telegram"),
    ("24afisha.by", "afisha"),
)


class SourceValidationError(ValueError):
    pass


def normalize_source_url(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or "." not in parsed.netloc:
        raise SourceValidationError("Ссылка выглядит неправильно")
    if len(value) > 512:
        raise SourceValidationError("Ссылка длиннее 512 символов")
    return value


def detect_source_kind(url: str | None) -> str | None:
    """Instagram / ВК / Telegram / 24afisha by host; any other link is a plain site."""
    if not url:
        return None
    host = (urlparse(url).hostname or "").lower()
    for suffix, kind in _HOST_KINDS:
        if host == suffix or host.endswith("." + suffix):
            return kind
    return "site"


def effective_fetch_mode(
    explicit: str | None, parser_key: str | None, requires_by_egress: bool, job_enabled: bool = True
) -> tuple[str, bool]:
    """(mode, set_by_admin). No explicit row: derive from the parser job.

    A switched-off job means nobody polls the source, so the schedule is entered by hand.
    """
    if explicit in FETCH_MODES:
        return explicit, True
    if parser_key is None:
        return "none", False
    if not job_enabled:
        return "manual", False
    if parser_key == "manual_schedule_v1":
        return "manual", False
    return ("byip" if requires_by_egress else "server"), False


def health_status(
    mode: str, failure_streak: int, last_error_code: str | None, future_sessions: int
) -> str:
    """ok | broken | empty | waiting | none — what the registry tile shows."""
    if mode == "none":
        return "none"
    if mode in ("manual", "byip"):
        # The server does not poll these; only the data we actually have counts.
        return "ok" if future_sessions > 0 else "waiting"
    if failure_streak >= BROKEN_STREAK and not (last_error_code or "").startswith("empty"):
        return "broken"
    if future_sessions == 0 or (last_error_code or "").startswith("empty"):
        return "empty"
    return "ok"


_LIST_SQL = text(
    """
    SELECT a.id AS arena_id, a.name, c.name AS city_name, p.slug,
           s.fetch_mode AS explicit_mode, s.source_url, s.source_kind,
           COALESCE(s.publish_days, '{}'::smallint[]) AS publish_days, COALESCE(s.remind, false) AS remind,
           j.parser_key, j.is_enabled AS job_enabled, j.config, j.last_ok_at, COALESCE(j.failure_streak, 0) AS failure_streak,
           j.last_error_code,
           COALESCE(f.future_count, 0) AS future_sessions, f.last_date,
           ev.last_added_at, COALESCE(ev.added_7d, 0) AS added_7d, COALESCE(ev.removed_7d, 0) AS removed_7d,
           (SELECT started_at FROM ice_session_journal_meta LIMIT 1) AS journal_started_at
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN arena_schedule_sources s ON s.arena_id = a.id
    LEFT JOIN ice_parser_jobs j ON j.arena_id = a.id
    LEFT JOIN LATERAL (
        SELECT COUNT(*) FILTER (WHERE i.local_date >= CURRENT_DATE)::int AS future_count,
               MAX(i.local_date) AS last_date
        FROM ice_sessions i WHERE i.arena_id = a.id AND i.status = 'active'
    ) f ON true
    LEFT JOIN LATERAL (
        SELECT MAX(e.occurred_at) FILTER (WHERE e.event = 'added') AS last_added_at,
               COUNT(*) FILTER (WHERE e.event = 'added' AND e.occurred_at >= now() - interval '7 days')::int AS added_7d,
               COUNT(*) FILTER (WHERE e.event = 'removed' AND e.occurred_at >= now() - interval '7 days')::int AS removed_7d
        FROM ice_session_events e WHERE e.arena_id = a.id
    ) ev ON true
    WHERE a.is_active AND a.venue_type = 'ice' AND c.country = 'BY'
      AND (p.status IS NULL OR p.status = 'published')
      AND a.id <> ALL(:hidden)
    ORDER BY c.sort_order, c.id, a.id
    """
)

_STATUS_ORDER = {"broken": 0, "stale": 1, "empty": 2, "waiting": 3, "none": 4, "ok": 5}


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _links(row: Any) -> dict[str, str | None]:
    settings = Settings()
    base = (settings.webapp_base_url or "").strip().rstrip("/")
    site = place_page_url(base_url=base, city_name=row.city_name, slug=row.slug) if base and row.slug else None
    app = telegram_bot_start_link(
        client_bot_username=settings.client_bot_username, start_param=place_start_param(row.arena_id)
    )
    return {"site": site, "app": app}


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def staleness(
    mode: str, last_added_at: datetime | None, journal_started_at: datetime | None, now: datetime
) -> tuple[bool, int | None]:
    """(stale, whole days without new slots).

    Counted from the last «added» event; before there is one — from the day the journal started,
    so the first week after the rollout does not light up every rink. «none» (source not found
    yet) has its own group and never goes stale.
    """
    reference = _aware(last_added_at) or _aware(journal_started_at)
    if reference is None:
        return False, None
    age = now - reference
    return (mode != "none" and age >= STALE_AFTER), max(age.days, 0)


def build_source_item(row: Any, now: datetime | None = None) -> dict[str, Any]:
    config = row.config if isinstance(row.config, dict) else {}
    mode, explicit = effective_fetch_mode(
        row.explicit_mode, row.parser_key, bool(config.get("requires_by_egress")), row.job_enabled is not False
    )
    now = now or datetime.now(timezone.utc)
    status = health_status(mode, int(row.failure_streak), row.last_error_code, int(row.future_sessions))
    stale, days_since_added = staleness(mode, row.last_added_at, row.journal_started_at, now)
    if stale and status not in ("broken", "none"):
        status = "stale"
    return {
        "arena_id": row.arena_id,
        "name": row.name,
        "city": row.city_name,
        "mode": mode,
        "mode_set_by_admin": explicit,
        "source_url": row.source_url,
        "source_kind": row.source_kind or detect_source_kind(row.source_url),
        "publish_days": sorted(int(d) for d in (row.publish_days or [])),
        "remind": bool(row.remind),
        "status": status,
        "stale": stale,
        "days_since_added": days_since_added,
        "last_added_at": _iso(row.last_added_at),
        "added_7d": int(row.added_7d),
        "removed_7d": int(row.removed_7d),
        "failure_streak": int(row.failure_streak),
        "last_error_code": row.last_error_code,
        "last_ok_at": _iso(row.last_ok_at),
        "parser_key": row.parser_key,
        "future_sessions": int(row.future_sessions),
        "last_session_date": _iso(row.last_date),
        "links": _links(row),
    }


async def list_admin_ice_sources(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(_LIST_SQL, {"hidden": list(HIDDEN_ARENA_IDS)})).all()
    now = datetime.now(timezone.utc)
    items = [build_source_item(r, now) for r in rows]
    items.sort(key=lambda i: _STATUS_ORDER[i["status"]])  # stable: city order is kept inside a status
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    journal_started = rows[0].journal_started_at if rows else None
    return {
        "total": len(items), "counts": counts, "items": items,
        "journal_started_at": _iso(journal_started),
    }


async def save_admin_ice_source(
    session: AsyncSession,
    *,
    arena_id: int,
    source_url: str | None,
    fetch_mode: str,
    publish_days: list[int],
    remind: bool,
    admin_telegram_id: int | None,
) -> bool:
    """Upsert the admin's record. Returns False when the arena does not exist."""
    if fetch_mode not in FETCH_MODES:
        raise SourceValidationError("Неизвестный режим")
    days = sorted({int(d) for d in publish_days})
    if any(d < 0 or d > 6 for d in days):
        raise SourceValidationError("День недели должен быть от 0 до 6")
    url = normalize_source_url(source_url)
    exists = (await session.execute(text("SELECT 1 FROM arenas WHERE id = :a"), {"a": arena_id})).first()
    if exists is None:
        return False
    await session.execute(
        text(
            """
            INSERT INTO arena_schedule_sources
                (arena_id, source_url, source_kind, fetch_mode, publish_days, remind, updated_by)
            VALUES (:a, :url, :kind, :mode, :days, :remind, :by)
            ON CONFLICT (arena_id) DO UPDATE SET
                source_url = EXCLUDED.source_url, source_kind = EXCLUDED.source_kind,
                fetch_mode = EXCLUDED.fetch_mode, publish_days = EXCLUDED.publish_days,
                remind = EXCLUDED.remind, updated_at = now(), updated_by = EXCLUDED.updated_by
            """
        ),
        {
            "a": arena_id, "url": url, "kind": detect_source_kind(url), "mode": fetch_mode,
            "days": days, "remind": bool(remind), "by": admin_telegram_id,
        },
    )
    await session.commit()
    return True


# ── Журнал слотов ────────────────────────────────────────────────────────

_VISIBLE_ARENAS_SQL = text(
    """
    SELECT a.id AS arena_id, a.name, c.id AS city_id, c.name AS city_name
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    WHERE a.is_active AND a.venue_type = 'ice' AND c.country = 'BY'
      AND (p.status IS NULL OR p.status = 'published')
      AND a.id <> ALL(:hidden)
    ORDER BY c.sort_order, c.id, a.id
    """
)

_EVENTS_SQL = text(
    """
    SELECT e.id, e.arena_id, e.occurred_at, e.event, e.kind, e.local_date, e.starts_at_local,
           e.ends_at_local, e.source
    FROM ice_session_events e
    WHERE e.occurred_at >= :since AND e.occurred_at < :until
      AND e.arena_id = ANY(:arena_ids)
      AND (CAST(:source AS text) IS NULL OR e.source = :source)
    ORDER BY e.occurred_at DESC, e.id DESC
    LIMIT :limit
    """
)


def log_bounds(
    *, days: int = 7, date_from: date | None = None, date_to: date | None = None, today: date | None = None
) -> tuple[date, date]:
    """Local (Minsk) first and last day of the window. «7 дней» = today and the 6 days before."""
    today = today or datetime.now(_MINSK).date()
    if date_from is not None:
        last = date_to or today
        if last < date_from:
            raise SourceValidationError("Дата «по» раньше даты «с»")
        if (last - date_from).days + 1 > LOG_MAX_DAYS:
            raise SourceValidationError(f"Период не длиннее {LOG_MAX_DAYS} дней")
        return date_from, last
    days = max(1, min(int(days), LOG_MAX_DAYS))
    return today - timedelta(days=days - 1), today


def _slot(row: Any) -> dict[str, Any]:
    return {
        "date": row.local_date.isoformat(),
        "start": row.starts_at_local.strftime("%H:%M"),
        "end": row.ends_at_local.strftime("%H:%M"),
        "kind": row.kind,
    }


def group_batches(rows: list[Any], arenas: dict[int, Any]) -> list[dict[str, Any]]:
    """One batch = one write transaction on one arena (a parser run, an admin save)."""
    batches: dict[tuple[int, datetime, str], dict[str, Any]] = {}
    order: list[tuple[int, datetime, str]] = []
    for row in rows:
        key = (row.arena_id, row.occurred_at, row.source)
        if key not in batches:
            local = _aware(row.occurred_at).astimezone(_MINSK)
            arena = arenas[row.arena_id]
            batches[key] = {
                "at": local.isoformat(), "day": local.date().isoformat(), "time": local.strftime("%H:%M"),
                "arena_id": row.arena_id, "arena": arena.name, "city": arena.city_name, "source": row.source,
                "added": [], "removed": [], "changed": [],
            }
            order.append(key)
        batches[key][row.event].append(_slot(row))
    result = [batches[k] for k in order]
    for batch in result:
        for name in ("added", "removed", "changed"):
            batch[name].sort(key=lambda s: (s["date"], s["start"]))
    return result


async def _load_events(
    session: AsyncSession, *, arena_ids: list[int], first: date, last: date, source: str | None
) -> list[Any]:
    since = datetime.combine(first, time.min, tzinfo=_MINSK)
    until = datetime.combine(last + timedelta(days=1), time.min, tzinfo=_MINSK)
    return list(
        (
            await session.execute(
                _EVENTS_SQL,
                {"since": since, "until": until, "arena_ids": arena_ids, "source": source, "limit": LOG_MAX_EVENTS + 1},
            )
        ).all()
    )


def _check_source(source: str | None) -> str | None:
    if source in (None, ""):
        return None
    if source not in LOG_SOURCES:
        raise SourceValidationError("Неизвестный источник")
    return source


async def arena_log(
    session: AsyncSession, arena_id: int, *, days: int = 7, date_from: date | None = None, date_to: date | None = None
) -> dict[str, Any] | None:
    """Journal of one arena. None when the arena is not in the admin list."""
    first, last = log_bounds(days=days, date_from=date_from, date_to=date_to)
    arenas = {r.arena_id: r for r in (await session.execute(_VISIBLE_ARENAS_SQL, {"hidden": list(HIDDEN_ARENA_IDS)})).all()}
    if arena_id not in arenas:
        return None
    rows = await _load_events(session, arena_ids=[arena_id], first=first, last=last, source=None)
    truncated = len(rows) > LOG_MAX_EVENTS
    return {
        "arena_id": arena_id, "from": first.isoformat(), "to": last.isoformat(), "truncated": truncated,
        "batches": group_batches(rows[:LOG_MAX_EVENTS], arenas),
    }


async def journal(
    session: AsyncSession,
    *,
    days: int = 7,
    date_from: date | None = None,
    date_to: date | None = None,
    city_id: int | None = None,
    arena_id: int | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Общий журнал: все арены админки, фильтры по периоду, городу, арене и источнику."""
    first, last = log_bounds(days=days, date_from=date_from, date_to=date_to)
    source = _check_source(source)
    visible = (await session.execute(_VISIBLE_ARENAS_SQL, {"hidden": list(HIDDEN_ARENA_IDS)})).all()
    arenas = {r.arena_id: r for r in visible}
    scope = [
        r.arena_id for r in visible
        if (city_id is None or r.city_id == city_id) and (arena_id is None or r.arena_id == arena_id)
    ]
    rows = await _load_events(session, arena_ids=scope, first=first, last=last, source=source) if scope else []
    truncated = len(rows) > LOG_MAX_EVENTS
    rows = rows[:LOG_MAX_EVENTS]
    batches = group_batches(rows, arenas)
    touched = {b["arena_id"] for b in batches}
    return {
        "from": first.isoformat(), "to": last.isoformat(), "truncated": truncated,
        "totals": {
            "added": sum(1 for r in rows if r.event == "added"),
            "removed": sum(1 for r in rows if r.event == "removed"),
            "arenas": len(touched),
        },
        "batches": batches,
        "quiet": [
            {"arena_id": r.arena_id, "name": r.name, "city": r.city_name}
            for r in visible if r.arena_id in scope and r.arena_id not in touched
        ],
        "filters": {
            "cities": [
                {"id": cid, "name": name}
                for cid, name in dict.fromkeys((r.city_id, r.city_name) for r in visible)
            ],
            "arenas": [{"id": r.arena_id, "name": r.name, "city_id": r.city_id} for r in visible],
            "sources": list(LOG_SOURCES),
        },
    }
