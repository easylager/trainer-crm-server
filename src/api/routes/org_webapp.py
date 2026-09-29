"""Org webapp (TASK-141/EPIC5 TASK-105): director/operator Mini App backend.
New module — do not grow webapp.py."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_org_miniapp_principal
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.shared.config import Settings

router = APIRouter(prefix="/api/webapp/org", tags=["webapp-org"])


async def _require_org_operator(
    session: AsyncSession,
    principal: MiniAppPrincipal,
    *,
    collective_slug: str | None = None,
) -> Any:
    """Any active operator role (owner or admin). 404 mirrors trainer bootstrap's precedent."""
    from src.application.collective_use_cases import resolve_operator_membership

    membership = await resolve_operator_membership(
        session,
        principal.user_id,
        collective_slug=collective_slug,
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Not an operator of any school")
    return membership


@router.get("/bootstrap")
async def get_org_bootstrap(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """Operator session bootstrap: collective context + role. 404 when no operator row exists."""
    membership = await _require_org_operator(session, principal)
    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "display_name": membership.display_name,
        "status": membership.status,
        "role": membership.role,
    }


@router.get("/collective/subscription")
async def get_org_collective_subscription(
    collective_slug: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S2 (TASK-112): subscription visibility for the org's own owner/admin.

    Read-only by design for the pilot: activation itself goes through the platform-admin
    console (manual grant — TASK-113/``admin_grant_collective_subscription``), which is
    already the production-safe path when a payment gateway doesn't cover the org's country.
    """
    from src.application.collective_use_cases import get_collective_subscription_status

    membership = await _require_org_operator(session, principal, collective_slug=collective_slug)
    status = await get_collective_subscription_status(session, collective_id=membership.collective_id)
    active = status.get("active_subscription") if status is not None else None
    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "role": membership.role,
        "has_active_subscription": active is not None,
        "active": active,
        "support_url": Settings().subscription_support_url,
    }


class OrgProfileContactsPatch(BaseModel):
    phone: str | None = None
    telegram: str | None = None


class OrgProfilePatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=128)
    about: str | None = Field(None, max_length=4000)
    clear_about: bool = False
    contacts: OrgProfileContactsPatch | None = None


@router.get("/profile")
async def get_org_profile(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S3: school profile + readiness checklist for the onboarding screen."""
    from src.application.collective_use_cases import get_org_collective_profile_payload

    membership = await _require_org_operator(session, principal)
    payload = await get_org_collective_profile_payload(session, membership.collective_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="School not found")
    payload["role"] = membership.role
    return payload


@router.patch("/profile")
async def patch_org_profile(
    body: OrgProfilePatch,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S3: owner-only edit of name/about/contact — see scope note on the use-case."""
    from src.application.collective_use_cases import update_org_collective_profile_for_operator

    membership = await _require_org_operator(session, principal)
    contacts = body.contacts.model_dump(exclude_none=True) if body.contacts is not None else None
    result = await update_org_collective_profile_for_operator(
        session,
        collective_id=membership.collective_id,
        telegram_id=principal.user_id,
        display_name=body.display_name,
        about=body.about,
        clear_about=body.clear_about,
        contacts=contacts,
    )
    error = result.get("error")
    if error == "owner_only":
        raise HTTPException(status_code=403, detail="Owner only")
    if error == "display_name_required":
        raise HTTPException(status_code=422, detail="display_name is required")
    if error:
        raise HTTPException(status_code=400, detail=error)
    result["role"] = membership.role
    return result
