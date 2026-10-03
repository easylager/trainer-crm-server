"""
Потребительская аналитика каталога: просмотры публички, клик «Открыть в Telegram», вход в мини-апп.

Отдельно от ``client_share_events`` (намерение отправить) и ``trainer_demand_events`` (Lead Mode).
Без PII: только ``actor_hash`` (telegram user / день или IP+UA / день на публичке).
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_deep_links import is_catalog_deep_link
from src.application.place_links import is_valid_start_param

logger = logging.getLogger(__name__)

KIND_PUBLIC_PAGE_VIEW = "public_page_view"
KIND_PUBLIC_TELEGRAM_CTA = "public_telegram_cta"
KIND_MINIAPP_CATALOG_ENTRY = "miniapp_catalog_entry"

CATALOG_CONSUMER_KINDS = (
    KIND_PUBLIC_PAGE_VIEW,
    KIND_PUBLIC_TELEGRAM_CTA,
    KIND_MINIAPP_CATALOG_ENTRY,
)

SURFACE_PLACE_PAGE = "place_page"
SURFACE_SELECTION_PAGE = "selection_page"
SURFACE_ICE_CITY_DAY = "ice_city_day"
SURFACE_MINIAPP_ICE = "miniapp_ice"
SURFACE_MINIAPP_ARENA = "miniapp_arena"
SURFACE_MINIAPP_SHELL = "miniapp_shell"


def public_actor_hash(*, client_ip: str | None, user_agent: str | None, day: date) -> str | None:
    if not client_ip and not user_agent:
        return None
    raw = f"pub|{(client_ip or '').strip()}|{(user_agent or '').strip()[:200]}|{day.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def telegram_actor_hash(telegram_id: int | str, day: date) -> str:
    raw = f"tg|{int(telegram_id)}|catalog|{day.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def event_dedup_hash(*, kind: str, surface: str, actor_hash: str | None, day: date) -> str | None:
    if not actor_hash:
        return None
    raw = f"{kind}|{surface}|{actor_hash}|{day.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_share_deeplink_start_param(start_param: str | None) -> bool:
    return is_catalog_deep_link((start_param or "").strip() or None)


async def record_catalog_consumer_event(
    session: AsyncSession,
    *,
    kind: str,
    surface: str,
    actor_hash: str | None = None,
    city_id: int | None = None,
    arena_id: int | None = None,
    start_param: str | None = None,
    payload: dict[str, Any] | None = None,
    dedup: bool = True,
) -> bool:
    """Append one row. Returns True if inserted. Never raises into HTTP handlers."""
    if kind not in CATALOG_CONSUMER_KINDS:
        raise ValueError(f"Unknown catalog consumer kind: {kind!r}")
    sp = (start_param or "").strip() or None
    if sp and not is_valid_start_param(sp):
        sp = None
    day = datetime.now(timezone.utc).date()
    body = dict(payload or {})
    if sp and is_share_deeplink_start_param(sp):
        body.setdefault("share_deeplink", True)
    dedup_hash = event_dedup_hash(kind=kind, surface=surface, actor_hash=actor_hash, day=day) if dedup else None
    if dedup and dedup_hash:
        exists = await session.execute(
            text(
                """
                SELECT 1 FROM catalog_consumer_events
                WHERE kind = :kind AND surface = :surface AND actor_hash = :actor
                  AND occurred_at >= :day_start AND occurred_at < :day_end
                LIMIT 1
                """
            ),
            {
                "kind": kind,
                "surface": surface,
                "actor": actor_hash,
                "day_start": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
                "day_end": datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
            },
        )
        if exists.first() is not None:
            return False
    try:
        await session.execute(
            text(
                """
                INSERT INTO catalog_consumer_events
                    (kind, surface, actor_hash, city_id, arena_id, start_param, payload)
                VALUES
                    (:kind, :surface, :actor, :city_id, :arena_id, :start_param, CAST(:payload AS jsonb))
                """
            ),
            {
                "kind": kind,
                "surface": surface,
                "actor": actor_hash,
                "city_id": city_id,
                "arena_id": arena_id,
                "start_param": sp,
                "payload": json.dumps(body, ensure_ascii=False),
            },
        )
        await session.commit()
        return True
    except Exception:
        logger.exception("catalog_consumer_events insert failed kind=%s surface=%s", kind, surface)
        await session.rollback()
        return False


async def get_catalog_wau(
    session: AsyncSession,
    *,
    days: int = 7,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Уникальные ``actor_hash`` с просмотром публички или входом в мини-апп каталога."""
    as_of_dt = as_of or datetime.now(timezone.utc)
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    since = as_of_dt - timedelta(days=days)
    row = (
        await session.execute(
            text(
                """
                SELECT COUNT(DISTINCT actor_hash) AS wau
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND actor_hash IS NOT NULL
                  AND kind IN (:pv, :mini)
                """
            ),
            {
                "since": since,
                "as_of": as_of_dt,
                "pv": KIND_PUBLIC_PAGE_VIEW,
                "mini": KIND_MINIAPP_CATALOG_ENTRY,
            },
        )
    ).first()
    wau = int(row[0] or 0) if row else 0
    return {
        "metric": "catalog_wau",
        "days": days,
        "since": since.isoformat(),
        "as_of": as_of_dt.isoformat(),
        "unique_actors": wau,
    }


async def record_public_page_view(
    session: AsyncSession,
    request: Any,
    *,
    surface: str,
    city_id: int | None,
    arena_id: int | None = None,
) -> None:
    """GET /p/, /c/, ice today — один просмотр на actor в день (для WAU)."""
    from starlette.requests import Request

    if not isinstance(request, Request):
        return
    day = datetime.now(timezone.utc).date()
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_ip = forwarded[:64] if forwarded else (request.client.host if request.client else None)
    actor = public_actor_hash(
        client_ip=client_ip,
        user_agent=request.headers.get("user-agent"),
        day=day,
    )
    await record_catalog_consumer_event(
        session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        surface=surface,
        actor_hash=actor,
        city_id=city_id,
        arena_id=arena_id,
        payload={"path": str(request.url.path)},
    )


async def get_catalog_virality_cb_metrics(
    session: AsyncSession,
    *,
    days: int = 7,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    C-B прокси: shares/WAU и share→deeplink-open (мини-апп с arena_/catalog_ start_param).
    """
    as_of_dt = as_of or datetime.now(timezone.utc)
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    since = as_of_dt - timedelta(days=days)

    shares = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) AS events,
                       COUNT(DISTINCT actor_hash) AS sharers
                FROM client_share_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind IN ('place', 'selection', 'ice_city_day')
                """
            ),
            {"since": since, "as_of": as_of_dt},
        )
    ).first()

    deeplink_opens = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) AS events,
                       COUNT(DISTINCT actor_hash) AS actors
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :kind
                  AND start_param IS NOT NULL
                  AND (start_param LIKE 'arena_%' OR start_param LIKE 'catalog%')
                """
            ),
            {"since": since, "as_of": as_of_dt, "kind": KIND_MINIAPP_CATALOG_ENTRY},
        )
    ).first()

    cta_clicks = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :kind
                """
            ),
            {"since": since, "as_of": as_of_dt, "kind": KIND_PUBLIC_TELEGRAM_CTA},
        )
    ).scalar_one()

    wau = await get_catalog_wau(session, days=days, as_of=as_of_dt)
    share_events = int(shares[0] or 0) if shares else 0
    sharers = int(shares[1] or 0) if shares else 0
    open_events = int(deeplink_opens[0] or 0) if deeplink_opens else 0
    wau_n = int(wau["unique_actors"] or 0)

    return {
        "metric": "catalog_virality_cb",
        "days": days,
        "since": since.isoformat(),
        "as_of": as_of_dt.isoformat(),
        "share_events": share_events,
        "distinct_sharers": sharers,
        "catalog_wau": wau_n,
        "shares_per_wau": round(share_events / wau_n, 4) if wau_n else None,
        "public_telegram_cta_clicks": int(cta_clicks or 0),
        "miniapp_deeplink_entries": open_events,
        "share_to_deeplink_open_pct": round(100.0 * open_events / share_events, 1) if share_events else None,
    }
