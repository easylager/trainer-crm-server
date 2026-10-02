"""Org webapp (TASK-141/EPIC5 TASK-105): director/operator Mini App backend.
New module — do not grow webapp.py."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import get_org_miniapp_principal, get_org_miniapp_principal_multipart
from src.api.miniapp_auth.types import MiniAppPrincipal
from src.api.routes.webapp import ScheduleTemplateSlotBody, SlotEntryBody, _hhmm_strings_to_minutes
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
    primary_arena_id: int | None = None


@router.get("/profile")
async def get_org_profile(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S3: school profile + readiness checklist for the onboarding screen."""
    from src.application.catalog_use_cases import list_cities
    from src.application.collective_use_cases import get_org_collective_profile_payload

    membership = await _require_org_operator(session, principal)
    payload = await get_org_collective_profile_payload(session, membership.collective_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="School not found")
    payload["role"] = membership.role
    cities = await list_cities(session)
    payload["refs"] = {"cities": {"items": cities}}
    return payload


@router.get("/profile/arenas")
async def get_org_profile_arenas(
    city_id: int = Query(..., ge=1),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """TASK-143: arenas for the school's площадка picker — public confirmed catalog only."""
    from src.application.catalog_use_cases import list_arenas

    await _require_org_operator(session, principal)
    items = await list_arenas(session, city_id, include_unconfirmed=False)
    return {"items": items}


@router.patch("/profile")
async def patch_org_profile(
    body: OrgProfilePatch,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S3: owner-only edit of name/about/contact/площадка — see scope note on the use-case."""
    from src.application.collective_use_cases import update_org_collective_profile_for_operator

    membership = await _require_org_operator(session, principal)
    contacts = body.contacts.model_dump(exclude_none=True) if body.contacts is not None else None
    primary_arena_set = "primary_arena_id" in body.model_fields_set
    result = await update_org_collective_profile_for_operator(
        session,
        collective_id=membership.collective_id,
        telegram_id=principal.user_id,
        display_name=body.display_name,
        about=body.about,
        clear_about=body.clear_about,
        contacts=contacts,
        primary_arena_id=body.primary_arena_id,
        primary_arena_id_set=primary_arena_set,
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


@router.post("/profile/assets")
async def post_org_profile_asset(
    kind: str = Query(..., pattern="^(logo|cover|gallery)$"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal_multipart),
) -> dict[str, Any]:
    """TASK-143: owner uploads school logo, cover, or gallery photo."""
    from src.application.collective_use_cases import (
        get_org_collective_profile_payload,
        upload_collective_asset_for_operator,
    )

    membership = await _require_org_operator(session, principal)
    content_type = file.content_type or "image/jpeg"
    body_bytes = await file.read()
    uploaded = await upload_collective_asset_for_operator(
        session,
        collective_id=membership.collective_id,
        telegram_id=principal.user_id,
        body=body_bytes,
        content_type=content_type,
        kind=kind,
    )
    err = uploaded.get("error")
    if err == "owner_only":
        raise HTTPException(status_code=403, detail="Owner only")
    if err == "too_large":
        raise HTTPException(status_code=413, detail="File too large")
    if err == "not_image":
        raise HTTPException(status_code=400, detail="Not a valid image")
    if err == "gallery_full":
        raise HTTPException(status_code=409, detail="Gallery full")
    if err == "storage":
        raise HTTPException(status_code=503, detail="Storage temporarily unavailable")
    if err:
        raise HTTPException(status_code=403, detail=str(err))

    profile = await get_org_collective_profile_payload(session, membership.collective_id)
    if profile is not None:
        profile["role"] = membership.role
    return {"asset": uploaded, "profile": profile}


@router.get("/catalog")
async def get_org_catalog(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S5: catalog publication screen — state, preview, readiness checklist, history."""
    from src.application.collective_catalog_view import build_collective_catalog_screen_payload

    membership = await _require_org_operator(session, principal)
    payload = await build_collective_catalog_screen_payload(session, membership.collective_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="School not found")
    payload["role"] = membership.role
    return payload


@router.post("/catalog/publish")
async def post_org_catalog_publish(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S5: owner publishes the school's card — blocked while the profile checklist is open."""
    from src.application.collective_catalog_state import (
        COLLECTIVE_CATALOG_ACTOR_OPERATOR,
        COLLECTIVE_CATALOG_STATE_PUBLISHED,
        REASON_OPERATOR_PUBLISHED,
        CollectiveCatalogStateTransitionError,
        set_collective_catalog_state,
    )
    from src.application.collective_catalog_view import build_collective_catalog_screen_payload
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")

    profile = await build_collective_catalog_screen_payload(session, membership.collective_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="School not found")
    if not profile["readiness"]["ready"]:
        raise HTTPException(status_code=422, detail="Profile checklist is not complete")

    try:
        await set_collective_catalog_state(
            session,
            membership.collective_id,
            COLLECTIVE_CATALOG_STATE_PUBLISHED,
            reason=REASON_OPERATOR_PUBLISHED,
            actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR,
            actor_id=principal.user_id,
        )
    except CollectiveCatalogStateTransitionError:
        raise HTTPException(status_code=409, detail="Transition not allowed") from None

    return await build_collective_catalog_screen_payload(session, membership.collective_id)


@router.post("/catalog/hide")
async def post_org_catalog_hide(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S5: owner unpublishes the school's card."""
    from src.application.collective_catalog_state import (
        COLLECTIVE_CATALOG_ACTOR_OPERATOR,
        COLLECTIVE_CATALOG_STATE_HIDDEN,
        REASON_OPERATOR_HIDDEN,
        CollectiveCatalogStateTransitionError,
        set_collective_catalog_state,
    )
    from src.application.collective_catalog_view import build_collective_catalog_screen_payload
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")

    try:
        changed = await set_collective_catalog_state(
            session,
            membership.collective_id,
            COLLECTIVE_CATALOG_STATE_HIDDEN,
            reason=REASON_OPERATOR_HIDDEN,
            actor_type=COLLECTIVE_CATALOG_ACTOR_OPERATOR,
            actor_id=principal.user_id,
        )
    except CollectiveCatalogStateTransitionError:
        raise HTTPException(status_code=409, detail="Transition not allowed") from None
    if not changed:
        raise HTTPException(status_code=404, detail="School not found")

    return await build_collective_catalog_screen_payload(session, membership.collective_id)


@router.get("/team")
async def get_org_team(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S4: coach roster (collective_members, joined) + count of outstanding invites.

    Pending invites are anonymous single-use links (col_inv_*) not tied to an
    identity until consumed, so they're surfaced as a count, not fabricated
    per-person "ждёт ответа" rows — see collective_use_cases.count_pending_collective_invite_tokens.
    """
    from src.application.collective_use_cases import (
        count_active_collective_members,
        count_pending_collective_invite_tokens,
        list_collective_members_for_studio,
    )

    membership = await _require_org_operator(session, principal)
    members = await list_collective_members_for_studio(session, membership.collective_id)
    active_count = await count_active_collective_members(session, membership.collective_id)
    pending_invites = await count_pending_collective_invite_tokens(session, membership.collective_id)
    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "role": membership.role,
        "members": members,
        "active_count": active_count,
        "pending_invites": pending_invites,
    }


@router.post("/team/invite")
async def post_org_team_invite(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S4: owner issues a one-time col_inv_* deep link for a new coach (DEC-002 —
    only viewing + invite in this pass, no promote/remove)."""
    from src.application.collective_use_cases import (
        OPERATOR_ROLE_OWNER,
        issue_collective_invite_token_for_operator,
    )

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")
    issued = await issue_collective_invite_token_for_operator(session, membership.collective_id)
    if issued is None:
        raise HTTPException(status_code=404, detail="School not found")
    if issued.get("error") == "seats_full":
        raise HTTPException(status_code=409, detail="Seats full")
    return {
        "invite_link": issued.get("deep_link"),
        "start_payload": issued.get("start_payload"),
        "expires_at": issued.get("expires_at"),
        "seat_limit": issued.get("seat_limit"),
        "active_count": issued.get("active_count"),
    }


# --- S6: Schedule (multi-trainer) ---


async def _require_trainer_in_collective(
    session: AsyncSession,
    collective_id: int,
    trainer_id: int,
) -> None:
    """Verify trainer is an active member of the collective."""
    from src.application.collective_use_cases import is_trainer_in_collective

    if not await is_trainer_in_collective(session, collective_id, trainer_id):
        raise HTTPException(status_code=404, detail="Trainer not found in collective")


@router.get("/schedule")
async def get_org_schedule(
    trainer_id: int = Query(..., description="Trainer whose schedule to load"),
    from_date: date | None = Query(None, description="YYYY-MM-DD"),
    to_date: date | None = Query(None, description="YYYY-MM-DD"),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: schedule for a specific trainer in the collective — same payload the
    trainer sees in their own schedule, built by the shared helper (webapp.py's
    ``get_schedule`` route calls the same function for its own principal)."""
    from src.api.routes.webapp import build_trainer_schedule_payload

    membership = await _require_org_operator(session, principal)
    await _require_trainer_in_collective(session, membership.collective_id, trainer_id)

    return await build_trainer_schedule_payload(
        session, trainer_id, from_date=from_date, to_date=to_date
    )


class OrgScheduleSlotsDayBody(BaseModel):
    trainer_id: int
    slot_date: str  # YYYY-MM-DD
    start_hours: list[int] | None = None
    start_times: list[str] | None = None
    duration_minutes: int = Field(default=45, ge=15, le=480)
    capacity: int = Field(default=1, ge=1, le=500)
    group_service_id: int | None = None
    arena_id: int | None = None
    slot_entries: list[SlotEntryBody] | None = None

    @model_validator(mode="after")
    def _one_time_source(self):
        sources = sum([
            self.start_times is not None,
            self.start_hours is not None,
            self.slot_entries is not None,
        ])
        if sources > 1:
            raise ValueError("Укажите только один способ: start_times, start_hours или slot_entries.")
        return self


class OrgScheduleTemplateDayBody(BaseModel):
    trainer_id: int
    day_of_week: int  # 0=Mon .. 6=Sun
    duration_minutes: int = Field(default=45, ge=15, le=480)
    start_hours: list[int] | None = None
    slots: list[ScheduleTemplateSlotBody] | None = None
    group_arena_id: int | None = None

    @model_validator(mode="after")
    def _normalize_slots(self):
        if self.slots is not None:
            return self
        self.slots = [ScheduleTemplateSlotBody(hour=h, minute=0, capacity=1) for h in (self.start_hours or [])]
        return self


class OrgScheduleApplyWeekBody(BaseModel):
    trainer_id: int
    week_start: str  # YYYY-MM-DD (Monday)


@router.get("/schedule/services")
async def get_org_schedule_trainer_services(
    trainer_id: int = Query(..., description="Trainer whose own services to list"),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """TASK-144: service picker for group-slot creation.

    "Offers" == present in ``trainer_services`` (same table ``trainer_offers_service``
    checks in ``post_org_schedule_slots``) — filtering the catalog list down to just the
    ids in ``get_trainer(...)['service_ids']`` guarantees the picker never shows a service
    the slot-create call would then reject.
    """
    from src.api.routes.webapp import get_trainer
    from src.application.catalog_use_cases import list_services

    membership = await _require_org_operator(session, principal)
    await _require_trainer_in_collective(session, membership.collective_id, trainer_id)
    trainer_row = await get_trainer(session, trainer_id)
    if trainer_row is None:
        raise HTTPException(status_code=404, detail="Trainer not found")
    own_ids = {int(x) for x in (trainer_row.get("service_ids") or [])}
    catalog = await list_services(session, owner_trainer_id=trainer_id, include_non_public=True)
    items = [s for s in catalog if int(s.get("id")) in own_ids]
    return {"items": items}


@router.post("/schedule/slots")
async def post_org_schedule_slots(
    body: OrgScheduleSlotsDayBody,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: create/update slots for a trainer in the collective (owner only)."""
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER
    from src.api.routes.webapp import (
        _schedule_slot_intervals,
        _require_schedule_arena_link,
        get_trainer,
        trainer_has_crm_access,
        trainer_offers_service,
        assert_no_center_duty_conflict_for_slots,
        replace_slots_for_day,
        invalidate_slots_for_trainer,
        _clear_slot_related_hint_snoozes,
        _bg_notify_slot_waitlist,
        WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED,
    )

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")
    await _require_trainer_in_collective(session, membership.collective_id, body.trainer_id)

    trainer_id = body.trainer_id

    # Require CRM tier
    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)

    if body.capacity > 1:
        trainer_row = await get_trainer(session, trainer_id) or {}
        if not bool((trainer_row.get("profile") or {}).get("group_classes_enabled")):
            raise HTTPException(
                status_code=400,
                detail="Включите «Групповые занятия» в профиле, чтобы создавать групповые слоты в календаре.",
            )
        if body.group_service_id is None:
            raise HTTPException(
                status_code=400,
                detail="Для группового слота укажите услугу.",
            )
        if not await trainer_offers_service(session, trainer_id, int(body.group_service_id)):
            raise HTTPException(status_code=400, detail="Услуга не в вашем списке")

    if body.arena_id is not None:
        await _require_schedule_arena_link(session, trainer_id, int(body.arena_id))

    try:
        slot_date = date.fromisoformat(body.slot_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid slot_date")

    arena_arg = int(body.arena_id) if body.arena_id is not None else None

    try:
        duty_intervals = _schedule_slot_intervals(body)
        if duty_intervals:
            await assert_no_center_duty_conflict_for_slots(
                session,
                trainer_id=trainer_id,
                slot_date=slot_date,
                intervals=duty_intervals,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if body.slot_entries is not None:
        per_slot: dict[int, int] = {}
        per_slot_arena: dict[int, int] = {}
        for entry in body.slot_entries:
            try:
                m_set = _hhmm_strings_to_minutes([entry.start_time])
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            start_m = next(iter(m_set))
            per_slot[start_m] = entry.duration_minutes
            if entry.arena_id is not None:
                if body.capacity != 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Площадку на уровне одного слота можно задать только для индивидуальных слотов.",
                    )
                aid_ent = int(entry.arena_id)
                await _require_schedule_arena_link(session, trainer_id, aid_ent)
                per_slot_arena[start_m] = aid_ent
        try:
            await replace_slots_for_day(
                session,
                trainer_id,
                slot_date,
                set(per_slot.keys()),
                duration_minutes=45,
                capacity=body.capacity,
                group_service_id=body.group_service_id,
                slot_arena_id=arena_arg,
                per_slot_duration=per_slot,
                per_slot_arena_id=per_slot_arena if per_slot_arena else None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if per_slot:
            background_tasks.add_task(_bg_notify_slot_waitlist, trainer_id)
        invalidate_slots_for_trainer(trainer_id)
        await _clear_slot_related_hint_snoozes(session, trainer_id)
        return {"ok": True, "trainer_id": trainer_id}

    if body.start_times is not None:
        try:
            minutes_set = _hhmm_strings_to_minutes(body.start_times)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    elif body.start_hours is not None:
        minutes_set = {h * 60 for h in body.start_hours if 0 <= h <= 23}
    else:
        minutes_set = set()

    try:
        await replace_slots_for_day(
            session,
            trainer_id,
            slot_date,
            minutes_set,
            body.duration_minutes,
            capacity=body.capacity,
            group_service_id=body.group_service_id,
            slot_arena_id=arena_arg,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if minutes_set:
        background_tasks.add_task(_bg_notify_slot_waitlist, trainer_id)

    invalidate_slots_for_trainer(trainer_id)
    await _clear_slot_related_hint_snoozes(session, trainer_id)
    return {"ok": True, "trainer_id": trainer_id}


@router.delete("/schedule/slots/{slot_id}")
async def delete_org_schedule_slot(
    slot_id: int,
    trainer_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: delete a slot for a trainer in the collective (owner only)."""
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER
    from src.api.routes.webapp import (
        schedule_delete_slot,
        invalidate_slots_for_trainer,
        trainer_has_crm_access,
        WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED,
    )

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")
    await _require_trainer_in_collective(session, membership.collective_id, trainer_id)

    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)

    deleted = await schedule_delete_slot(session, trainer_id, slot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Slot not found or booked")
    invalidate_slots_for_trainer(trainer_id)
    return {"ok": True}


@router.get("/schedule/templates")
async def get_org_schedule_templates(
    trainer_id: int = Query(...),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: weekly template entries for a trainer in the collective."""
    from src.api.routes.webapp import (
        list_templates,
        get_schedule_grid_preset_for_trainer,
        schedule_grid_preset_to_api,
    )

    membership = await _require_org_operator(session, principal)
    await _require_trainer_in_collective(session, membership.collective_id, trainer_id)

    templates = await list_templates(session, trainer_id)
    grid_preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    return {
        "trainer_id": trainer_id,
        "templates": [
            {
                "id": t["id"],
                "day_of_week": t["day_of_week"],
                "start_time": t["start_time"].strftime("%H:%M") if hasattr(t["start_time"], "strftime") else str(t["start_time"])[:5],
                "duration_minutes": t["duration_minutes"],
                "capacity": int(t.get("capacity") or 1),
                "service_id": t.get("service_id"),
                "arena_id": t.get("arena_id"),
            }
            for t in templates
        ],
        "schedule_grid": schedule_grid_preset_to_api(grid_preset),
    }


@router.put("/schedule/templates/day")
async def put_org_schedule_template_day(
    body: OrgScheduleTemplateDayBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: set template for one week day for a trainer in the collective (owner only) —
    same validation as the trainer's own template screen, via the shared helper."""
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER
    from src.api.routes.webapp import apply_trainer_schedule_template_day

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")
    await _require_trainer_in_collective(session, membership.collective_id, body.trainer_id)

    await apply_trainer_schedule_template_day(session, body.trainer_id, body)
    return {"ok": True}


@router.post("/schedule/apply-week")
async def post_org_schedule_apply_week(
    body: OrgScheduleApplyWeekBody,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S6: replace one week with template for a trainer in the collective (owner only)."""
    from src.application.collective_use_cases import OPERATOR_ROLE_OWNER
    from src.api.routes.webapp import (
        trainer_has_crm_access,
        replace_week_with_template,
        apply_recurring_bookings_for_week,
        WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED,
    )

    membership = await _require_org_operator(session, principal)
    if membership.role != OPERATOR_ROLE_OWNER:
        raise HTTPException(status_code=403, detail="Owner only")
    await _require_trainer_in_collective(session, membership.collective_id, body.trainer_id)

    trainer_id = body.trainer_id

    if not await trainer_has_crm_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_CRM_REQUIRED)

    try:
        week_start = date.fromisoformat(body.week_start)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid week_start")

    count = await replace_week_with_template(session, trainer_id, week_start)
    await apply_recurring_bookings_for_week(session, trainer_id, week_start)
    return {"ok": True, "slots_created": count}


# --- S7: Clients (aggregated across collective trainers) ---


@router.get("/clients")
async def get_org_clients(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_org_miniapp_principal),
) -> dict[str, Any]:
    """S7: aggregated client list across all active trainers in the collective."""
    from src.application.collective_use_cases import list_collective_clients

    membership = await _require_org_operator(session, principal)
    clients = await list_collective_clients(session, membership.collective_id)
    return {
        "collective_id": membership.collective_id,
        "slug": membership.slug,
        "role": membership.role,
        "clients": clients,
    }
