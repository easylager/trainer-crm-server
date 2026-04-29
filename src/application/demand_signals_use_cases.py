"""
Lead Mode demand signals: anonymous proof-of-demand for public-facing trainers.

Records views/clicks without storing any visitor identity. Aggregates over fixed time windows
(7d / 14d / 30d) for trainer-home recap UI and recovery nudge content.

Privacy contract:
- IP and User-Agent are never persisted in cleartext.
- The dedup_hash = sha256(client_ip || user_agent || trainer_id || YYYY-MM-DD) is stored only to
  collapse refresh-spam inside one calendar day. The hash is irreversible and the input window is
  too narrow to be PII under GDPR/Belarus data laws (irreducible cohort > 1).
- Anonymous=True for the entire pipeline; user-level tracking is an explicit anti-goal.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db.models import (
    DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED,
    DEMAND_EVENT_CATALOG_FAVORITE,
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_KINDS,
    DEMAND_EVENT_PROFILE_VIEW,
    DEMAND_SOURCES,
)
from src.infrastructure.repositories.demand_signals_repository import (
    DemandSignalsRepository,
)

logger = logging.getLogger(__name__)

# Standard recap windows. Keep small/explicit — not a DSL.
RECAP_WINDOW_7D = 7
RECAP_WINDOW_14D = 14
RECAP_WINDOW_30D = 30
SUPPORTED_RECAP_WINDOWS = (RECAP_WINDOW_7D, RECAP_WINDOW_14D, RECAP_WINDOW_30D)


@dataclass(frozen=True, slots=True)
class SignalsRecap:
    """Aggregated demand for one trainer over a window. UI-ready primitive (no rendering inside)."""

    trainer_id: int
    window_days: int
    since: datetime
    until: datetime
    profile_views: int
    contact_clicks: int
    booking_attempts_blocked: int
    catalog_favorites: int

    @property
    def has_any_demand(self) -> bool:
        return (
            self.profile_views > 0
            or self.contact_clicks > 0
            or self.booking_attempts_blocked > 0
            or self.catalog_favorites > 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "trainer_id": self.trainer_id,
            "window_days": self.window_days,
            "since": self.since.isoformat(),
            "until": self.until.isoformat(),
            "profile_views": self.profile_views,
            "contact_clicks": self.contact_clicks,
            "booking_attempts_blocked": self.booking_attempts_blocked,
            "catalog_favorites": self.catalog_favorites,
            "has_any_demand": self.has_any_demand,
        }


def compute_dedup_hash(
    *,
    client_ip: str | None,
    user_agent: str | None,
    trainer_id: int,
    when: datetime | None = None,
) -> str | None:
    """
    Build the daily dedup hash. Returns None if both ip and user_agent are missing — in that case
    we choose to NOT dedupe (better to over-count than to lose signal entirely).
    """
    if not client_ip and not user_agent:
        return None
    when = when or datetime.now(timezone.utc)
    day = when.astimezone(timezone.utc).strftime("%Y-%m-%d")
    raw = f"{(client_ip or '').strip()}|{(user_agent or '').strip()}|{trainer_id}|{day}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_source(source: str | None) -> str | None:
    """Reject unknown sources to keep the column queryable; None passes through."""
    if source is None:
        return None
    if source not in DEMAND_SOURCES:
        raise ValueError(f"Unknown demand source: {source!r}")
    return source


async def record_catalog_favorite(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """
    Record a catalog «heart» / bookmark save (client_trainer_edges.is_saved true transition).
    No dedup — each deliberate save is a signal; unsave+save again counts again.
    """
    repo = DemandSignalsRepository(session)
    return await repo.insert_event(
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_CATALOG_FAVORITE,
        source=_validate_source(source),
        dedup_hash=None,
        payload=payload,
    )


async def record_profile_view(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """
    Record a public-card view. Refresh storms inside one day are deduped via sha256(ip||ua||tid||day).
    Returns True if a row was inserted, False if it was a same-day duplicate.
    """
    repo = DemandSignalsRepository(session)
    return await repo.insert_event(
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_PROFILE_VIEW,
        source=_validate_source(source),
        dedup_hash=compute_dedup_hash(
            client_ip=client_ip, user_agent=user_agent, trainer_id=trainer_id
        ),
        payload=payload,
    )


async def record_profile_view_commit(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """
    Same as record_profile_view, then commits.

    Needed whenever the AsyncSession is not wrapped in an explicit request-scoped commit:
    - ``async with async_session_factory()`` only closes (rolls back uncommitted work).
    - FastAPI ``Depends(get_session)`` yields the same pattern unless the route commits.
    """
    inserted = await record_profile_view(
        session,
        trainer_id=trainer_id,
        source=source,
        client_ip=client_ip,
        user_agent=user_agent,
        payload=payload,
    )
    await session.commit()
    logger.debug(
        "demand_signals profile_view committed trainer_id=%s inserted=%s",
        trainer_id,
        inserted,
    )
    return inserted


async def record_contact_click(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """
    Record a Telegram-redirect click ("/r/tg/{trainer_id}"). Same-day dedup by (ip, ua, trainer_id)
    so that double-clicks count once.
    """
    repo = DemandSignalsRepository(session)
    return await repo.insert_event(
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_CONTACT_CLICK,
        source=_validate_source(source),
        dedup_hash=compute_dedup_hash(
            client_ip=client_ip, user_agent=user_agent, trainer_id=trainer_id
        ),
        payload=payload,
    )


async def record_contact_click_commit(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None,
    client_ip: str | None = None,
    user_agent: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Same as record_contact_click, then commits (see record_profile_view_commit)."""
    inserted = await record_contact_click(
        session,
        trainer_id=trainer_id,
        source=source,
        client_ip=client_ip,
        user_agent=user_agent,
        payload=payload,
    )
    await session.commit()
    logger.debug(
        "demand_signals contact_click committed trainer_id=%s inserted=%s",
        trainer_id,
        inserted,
    )
    return inserted


async def record_booking_attempt_blocked(
    session: AsyncSession,
    *,
    trainer_id: int,
    source: str | None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """
    Record that a client tried to open online booking for a trainer in Lead Mode and was blocked.
    Server-side event — no dedup, every attempt is a real loss signal.
    """
    repo = DemandSignalsRepository(session)
    return await repo.insert_event(
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED,
        source=_validate_source(source),
        dedup_hash=None,
        payload=payload,
    )


async def get_signals_recap(
    session: AsyncSession,
    *,
    trainer_id: int,
    window_days: int = RECAP_WINDOW_14D,
    now: datetime | None = None,
) -> SignalsRecap:
    """
    Aggregate the standard demand triplet (views / clicks / blocked bookings) for the last N days.
    Default window is 14d — matches the Lead Mode trainer-home recap card.
    """
    if window_days not in SUPPORTED_RECAP_WINDOWS:
        raise ValueError(
            f"Unsupported recap window: {window_days}. Use one of {SUPPORTED_RECAP_WINDOWS}."
        )

    until = now or datetime.now(timezone.utc)
    since = until - timedelta(days=window_days)

    repo = DemandSignalsRepository(session)
    counts = await repo.aggregate_window(
        trainer_id=trainer_id,
        kinds=DEMAND_EVENT_KINDS,
        since=since,
        until=until,
    )
    return SignalsRecap(
        trainer_id=trainer_id,
        window_days=window_days,
        since=since,
        until=until,
        profile_views=counts.get(DEMAND_EVENT_PROFILE_VIEW, 0),
        contact_clicks=counts.get(DEMAND_EVENT_CONTACT_CLICK, 0),
        booking_attempts_blocked=counts.get(DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED, 0),
        catalog_favorites=counts.get(DEMAND_EVENT_CATALOG_FAVORITE, 0),
    )


# Earliest possible lower bound: append-only log has no "before" events.
_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def get_signals_lifetime_totals(
    session: AsyncSession, *, trainer_id: int, now: datetime | None = None
) -> dict[str, int]:
    """
    All-time counts of catalog profile views and Telegram contact clicks.
    """
    # Note: COUNT over demand log — analytics dashboard only, not per hub request.
    until = now or datetime.now(timezone.utc)
    repo = DemandSignalsRepository(session)
    counts = await repo.aggregate_window(
        trainer_id=trainer_id,
        kinds=(DEMAND_EVENT_PROFILE_VIEW, DEMAND_EVENT_CONTACT_CLICK, DEMAND_EVENT_CATALOG_FAVORITE),
        since=_EPOCH_UTC,
        until=until,
    )
    return {
        "profile_views": int(counts.get(DEMAND_EVENT_PROFILE_VIEW, 0)),
        "contact_clicks": int(counts.get(DEMAND_EVENT_CONTACT_CLICK, 0)),
        "catalog_favorites_events": int(counts.get(DEMAND_EVENT_CATALOG_FAVORITE, 0)),
    }


async def get_signals_since(
    session: AsyncSession,
    *,
    trainer_id: int,
    since: datetime,
    now: datetime | None = None,
) -> SignalsRecap:
    """
    Same triplet as recap, but with a custom start (e.g. since lead_mode_entered_at) — used by
    recovery nudges to compute "X views since trial ended".
    """
    until = now or datetime.now(timezone.utc)
    if since > until:
        raise ValueError("since must be earlier than now/until")

    repo = DemandSignalsRepository(session)
    counts = await repo.aggregate_window(
        trainer_id=trainer_id,
        kinds=DEMAND_EVENT_KINDS,
        since=since,
        until=until,
    )
    window_days = max(1, int((until - since).total_seconds() // 86400))
    return SignalsRecap(
        trainer_id=trainer_id,
        window_days=window_days,
        since=since,
        until=until,
        profile_views=counts.get(DEMAND_EVENT_PROFILE_VIEW, 0),
        contact_clicks=counts.get(DEMAND_EVENT_CONTACT_CLICK, 0),
        booking_attempts_blocked=counts.get(DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED, 0),
        catalog_favorites=counts.get(DEMAND_EVENT_CATALOG_FAVORITE, 0),
    )


__all__ = [
    "SignalsRecap",
    "compute_dedup_hash",
    "record_profile_view",
    "record_profile_view_commit",
    "record_contact_click",
    "record_contact_click_commit",
    "record_booking_attempt_blocked",
    "get_signals_lifetime_totals",
    "get_signals_recap",
    "get_signals_since",
    "record_catalog_favorite",
    "RECAP_WINDOW_7D",
    "RECAP_WINDOW_14D",
    "RECAP_WINDOW_30D",
    "SUPPORTED_RECAP_WINDOWS",
]
