"""Admin «Источники расписаний»: where each Belarusian rink's schedule comes from.

The admin records the source link, how we collect it (server / own computer with a Belarusian
IP / manual check / none) and the weekdays the rink usually posts. Without a row the mode is
derived from ``ice_parser_jobs``, so the list is useful before anyone has edited anything.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.place_links import place_page_url, place_start_param, telegram_bot_start_link
from src.shared.config import Settings

FETCH_MODES = ("server", "byip", "manual", "none")
BROKEN_STREAK = 3

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
           COALESCE(f.future_count, 0) AS future_sessions, f.last_date
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
    WHERE a.is_active AND a.venue_type = 'ice' AND c.country = 'BY'
      AND (p.status IS NULL OR p.status = 'published')
    ORDER BY c.sort_order, c.id, a.id
    """
)

_STATUS_ORDER = {"broken": 0, "empty": 1, "waiting": 2, "none": 3, "ok": 4}


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


def build_source_item(row: Any) -> dict[str, Any]:
    config = row.config if isinstance(row.config, dict) else {}
    mode, explicit = effective_fetch_mode(
        row.explicit_mode, row.parser_key, bool(config.get("requires_by_egress")), row.job_enabled is not False
    )
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
        "status": health_status(mode, int(row.failure_streak), row.last_error_code, int(row.future_sessions)),
        "failure_streak": int(row.failure_streak),
        "last_error_code": row.last_error_code,
        "last_ok_at": _iso(row.last_ok_at),
        "parser_key": row.parser_key,
        "future_sessions": int(row.future_sessions),
        "last_session_date": _iso(row.last_date),
        "links": _links(row),
    }


async def list_admin_ice_sources(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.execute(_LIST_SQL)).all()
    items = [build_source_item(r) for r in rows]
    items.sort(key=lambda i: _STATUS_ORDER[i["status"]])  # stable: city order is kept inside a status
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"total": len(items), "counts": counts, "items": items}


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
