"""TASK-450 (этап 5.3): мои открытые компании — для главной v2, «Льда» v2 и «Я» v2.

Приватность компании: показываем только то, что пользователь и так видит —
компании, где он организатор (``organizer_ref``) или ответил «Иду»/«Может».
Имена — только из ответов этой компании. Чужая компания сюда не попадает никогда.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.ice_company.codes import tg_participant_key
from src.application.ice_company.copy import crowd_line
from src.application.style_b import b_photo_url

_MINSK = ZoneInfo("Europe/Minsk")

_SQL = text(
    """
    SELECT c.id AS company_id, c.public_code, c.name, c.organizer_ref, c.status AS company_status,
           e.kind AS event_kind, e.source_ref, e.starts_at, e.ends_at,
           e.venue_ref, e.venue_label, e.cancelled AS event_cancelled,
           a.id AS arena_id, a.name AS arena_name,
           COALESCE(p.timezone, 'Europe/Minsk') AS arena_tz,
           (
               SELECT m.variants
               FROM media m
               WHERE m.owner_type = 'arena' AND m.owner_id = a.id AND m.status = 'published'
               ORDER BY m.sort_order, m.id
               LIMIT 1
           ) AS photo_variants
    FROM ice_companies c
    JOIN ice_company_events e ON e.id = c.event_id
    LEFT JOIN arenas a ON a.id = CAST(substring(e.venue_ref FROM 'arena:(\\d+)') AS int)
    LEFT JOIN arena_profiles p ON p.arena_id = a.id
    WHERE c.status = 'open'
      AND NOT COALESCE(e.cancelled, false)
      AND e.ends_at > :now
      AND e.starts_at <= :horizon
      AND (
            c.organizer_ref = :me
            OR EXISTS (
                SELECT 1 FROM ice_company_responses r
                WHERE r.company_id = c.id AND r.participant_key = :me
                  AND r.status IN ('going', 'maybe')
            )
          )
    ORDER BY e.starts_at
    LIMIT :lim
    """
)

def _session_id(source_ref: str | None) -> int | None:
    prefix = "ice_session:"
    if not str(source_ref or "").startswith(prefix):
        return None
    raw = str(source_ref)[len(prefix) :]
    return int(raw) if raw.isdigit() else None


def _day_label(starts_local: datetime, today) -> str:
    d = starts_local.date()
    if d == today:
        return "сегодня"
    if d == today + timedelta(days=1):
        return "завтра"
    return starts_local.strftime("%a, %-d").lower() if hasattr(starts_local, "strftime") else str(d)


def _photo(raw: Any) -> dict[str, str | None]:
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    variants = raw if isinstance(raw, dict) else {}
    return {
        "thumb": b_photo_url(variants.get("thumb") or variants.get("card")),
        "card": b_photo_url(variants.get("card") or variants.get("thumb")),
    }


def _page_url(settings: Any, code: str) -> str:
    base = (getattr(settings, "webapp_base_url", "") or "").strip().rstrip("/")
    return f"{base}/k/{code}" if base else f"/k/{code}"


async def my_open_companies(
    session: AsyncSession,
    telegram_id: int,
    now: datetime,
    horizon_days: int = 7,
    *,
    limit: int = 5,
    settings: Any = None,
) -> list[dict[str, Any]]:
    """Открытые компании пользователя в горизонте ``horizon_days`` (свои и где «иду/может»)."""
    if settings is None:
        from src.shared.config import get_settings

        settings = get_settings()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    me = tg_participant_key(int(telegram_id))
    rows = (
        await session.execute(
            _SQL,
            {"me": me, "now": now, "horizon": now + timedelta(days=horizon_days), "lim": limit},
        )
    ).mappings().all()
    # ответы — одним запросом по всем компаниям
    codes = [str(r["public_code"]) for r in rows]
    resp_rows = (
        await session.execute(
            text(
                """
                SELECT r.company_id, r.participant_key, r.display_name, r.status
                FROM ice_company_responses r
                JOIN ice_companies c ON c.id = r.company_id
                WHERE c.public_code = ANY(:codes) AND r.status IN ('going', 'maybe')
                ORDER BY r.updated_at, r.id
                """
            ),
            {"codes": codes},
        )
    ).mappings().all() if codes else []
    by_company: dict[int, list[dict[str, Any]]] = {}
    for rr in resp_rows:
        by_company.setdefault(int(rr["company_id"]), []).append(dict(rr))
    result: list[dict[str, Any]] = []
    today = now.astimezone(_MINSK).date()
    for row in rows:
        cid = int(row["company_id"])
        resps = by_company.get(cid or -1, [])
        going = [r for r in resps if r["status"] == "going"]
        going_names = [str(r["display_name"]) for r in going if str(r["participant_key"]) != me][:3]
        mine = next((r for r in resps if str(r["participant_key"]) == me), None)
        my_status = "organizer" if str(row["organizer_ref"]) == me else (str(mine["status"]) if mine else "going")
        try:
            tz = ZoneInfo(str(row.get("arena_tz") or "Europe/Minsk"))
        except Exception:
            tz = _MINSK
        starts = row["starts_at"]
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        starts_local = starts.astimezone(tz)
        arena_id = row.get("arena_id")
        result.append(
            {
                "code": str(row["public_code"]),
                "name": str(row["name"] or ""),
                "session_id": _session_id(str(row.get("source_ref") or "")),
                "arena_id": int(arena_id) if arena_id is not None else None,
                "arena_name": str(row.get("arena_name") or row.get("venue_label") or ""),
                "starts_local": starts_local.strftime("%H:%M"),
                "day_label": _day_label(starts_local, today),
                "going_count": len(going),
                "going_names": going_names,
                "crowd_line": crowd_line(len(going)),
                "my_status": my_status,
                "page_url": _page_url(settings, str(row["public_code"])),
                "photo": _photo(row.get("photo_variants")),
            }
        )
    return result
