"""
Short tracking redirects (no auth, no /api prefix) — designed to be embedded directly into
public surfaces (Telegram CTAs, SMS, QR codes).

The whole module is one URL family: ``GET /r/tg/{trainer_id}`` — record an anonymous contact_click
demand signal, then 302-redirect to the trainer's Telegram. Failure modes never block the redirect
itself; the click is the user's primary intent and analytics is best-effort.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.middleware.http_limits import client_ip_from_request
from src.application.demand_signals_use_cases import record_contact_click_commit
from src.infrastructure.db.models import (
    DEMAND_SOURCE_BOT,
    DEMAND_SOURCE_CATALOG,
    DEMAND_SOURCE_CLIENT_APP,
    DEMAND_SOURCE_DIRECT_LINK,
    DEMAND_SOURCE_SEARCH,
    DEMAND_SOURCES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/r", tags=["redirects"])

# Telegram allows lowercase letters, digits, and underscores; min 5 chars (we mirror the actual rule
# rather than guessing). The DB column is `String(64)` and the bot validates input on entry, but we
# re-validate here because the redirect target is built into a URL.
_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")

# UA-truncation guard: avoid log spam / oversized hash inputs from rogue clients.
_UA_MAX_LEN = 512


def _normalize_telegram_username(raw: str | None) -> str | None:
    """Strip leading '@', validate format. Returns None on invalid input (treat as no username)."""
    if not raw:
        return None
    candidate = raw.strip().lstrip("@")
    if not _TELEGRAM_USERNAME_RE.fullmatch(candidate):
        return None
    return candidate


def _resolve_source_from_request(request: Request, query_source: str | None) -> str | None:
    """
    Pick a demand source. Explicit ?src= wins (validated against the whitelist), else infer from
    Referer header (catalog Mini App vs external link). Never a free-form string — keeps the
    'source' column queryable for analytics.
    """
    if query_source:
        if query_source in DEMAND_SOURCES:
            return query_source
        # Unknown source from query — quietly drop it; do not break the redirect.
        return None
    referer = (request.headers.get("referer") or "").lower()
    if "/webapp/catalog" in referer:
        return DEMAND_SOURCE_CATALOG
    if "/webapp/" in referer:
        return DEMAND_SOURCE_CLIENT_APP
    if "/api/" in referer:
        return DEMAND_SOURCE_BOT
    if referer:
        return DEMAND_SOURCE_SEARCH
    return DEMAND_SOURCE_DIRECT_LINK


@router.get("/tg/{trainer_id:int}")
async def telegram_contact_redirect(
    trainer_id: int,
    request: Request,
    src: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """
    Trackable Telegram CTA: records a contact_click demand signal, then 302-redirects to t.me.

    Fail-safe contract: any failure to write the demand signal is swallowed — the user's click
    must always reach Telegram. We only block the redirect if the trainer has no usable username.
    """
    r = await session.execute(
        text("SELECT telegram_username FROM trainers WHERE id = :tid"),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trainer not found")
    username = _normalize_telegram_username(row[0])
    if not username:
        # Trainer exists but has no Telegram username we can safely link to. Hide existence to
        # avoid a Telegram-username-missing oracle and return the same 404 as above.
        raise HTTPException(status_code=404, detail="Trainer not found")

    source = _resolve_source_from_request(request, src)
    client_ip = client_ip_from_request(request)
    user_agent = (request.headers.get("user-agent") or "")[:_UA_MAX_LEN]

    # Best-effort signal recording. The click is a non-revertable user intent; we never let
    # analytics throw the redirect off course. We log at warning so missing signals are visible
    # in Sentry without polluting normal traffic.
    try:
        await record_contact_click_commit(
            session,
            trainer_id=trainer_id,
            source=source,
            client_ip=client_ip,
            user_agent=user_agent,
            payload={"redirect_to": "telegram"},
        )
    except Exception as exc:  # pragma: no cover — defensive; covered indirectly by observability
        logger.warning(
            "demand_signals.record_contact_click_commit failed for trainer_id=%s: %s",
            trainer_id,
            exc,
        )

    # Build the deep link. We use the t.me HTTPS form (works on web and triggers tg:// on mobile).
    # urlencode keeps the query string safe even if `src` is None.
    target_qs = urlencode({"src": source}) if source else ""
    target = f"https://t.me/{quote(username, safe='')}"
    if target_qs:
        target = f"{target}?{target_qs}"
    # 302 (not 301): we want this URL to remain "live" so the next click also records a signal.
    return RedirectResponse(url=target, status_code=302)


__all__ = ["router"]
