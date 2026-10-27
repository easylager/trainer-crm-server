"""First fill of ``arena_schedule_sources`` so the admin list is not empty on day one.

Rules, in order, per Belarusian ice rink:
1. An owner override (``data/ice-sources-overrides.json``) wins and is applied once.
2. An arena that already has a row keeps it: the admin's edits are never overwritten.
3. Otherwise the row copies the card's website link and the mode derived from the parser job
   (no parser → «разобраться вручную», i.e. mode ``none``).
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.admin_ice_sources import detect_source_kind, effective_fetch_mode, normalize_source_url

_ROWS_SQL = text(
    """
    SELECT a.id AS arena_id, a.name, c.name AS city, p.website_url,
           j.parser_key, j.is_enabled AS job_enabled, j.config, (s.arena_id IS NOT NULL) AS has_row
    FROM arenas a
    JOIN arena_profiles p ON p.arena_id = a.id
    JOIN cities c ON c.id = a.city_id
    LEFT JOIN ice_parser_jobs j ON j.arena_id = a.id
    LEFT JOIN arena_schedule_sources s ON s.arena_id = a.id
    WHERE a.is_active AND a.venue_type = 'ice' AND c.country = 'BY'
      AND (p.status IS NULL OR p.status = 'published')
    ORDER BY c.sort_order, c.id, a.id
    """
)


def plan_row(row: Any, override: dict | None, fallback_url: str | None = None) -> dict[str, Any] | None:
    """What to write for one arena, or None to leave it alone."""
    if override:
        url = normalize_source_url(override.get("source_url"))
        return {"arena_id": row.arena_id, "source_url": url, "fetch_mode": override["fetch_mode"],
                "origin": "override"}
    if row.has_row:
        return None
    config = row.config if isinstance(row.config, dict) else {}
    mode, _ = effective_fetch_mode(
        None, row.parser_key, bool(config.get("requires_by_egress")), getattr(row, "job_enabled", True) is not False
    )
    url = None
    for candidate in (row.website_url, fallback_url):  # the card link first, then the parser registry
        try:
            url = normalize_source_url(candidate)
        except ValueError:
            url = None
        if url:
            break
    return {"arena_id": row.arena_id, "source_url": url, "fetch_mode": mode, "origin": "card"}


async def plan_seed(
    session: AsyncSession, overrides: dict[str, dict], fallback_urls: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    rows = (await session.execute(_ROWS_SQL)).all()
    plan: list[dict[str, Any]] = []
    for r in rows:
        item = plan_row(r, overrides.get(str(r.arena_id)), (fallback_urls or {}).get(str(r.arena_id)))
        if item is not None:
            plan.append({**item, "name": r.name, "city": r.city, "parser_key": r.parser_key})
    return plan


async def apply_seed(session: AsyncSession, plan: list[dict[str, Any]]) -> int:
    for item in plan:
        await session.execute(
            text(
                """
                INSERT INTO arena_schedule_sources (arena_id, source_url, source_kind, fetch_mode)
                VALUES (:a, :url, :kind, :mode)
                ON CONFLICT (arena_id) DO UPDATE SET
                    source_url = EXCLUDED.source_url, source_kind = EXCLUDED.source_kind,
                    fetch_mode = EXCLUDED.fetch_mode, updated_at = now()
                WHERE :override
                """
            ),
            {"a": item["arena_id"], "url": item["source_url"], "kind": detect_source_kind(item["source_url"]),
             "mode": item["fetch_mode"], "override": item["origin"] == "override"},
        )
    await session.commit()
    return len(plan)
