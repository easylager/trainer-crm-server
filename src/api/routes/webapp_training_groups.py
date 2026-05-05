"""Trainer training groups (cohorts): CRUD, roster, join requests, client apply."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth.deps import miniapp_credential_http_exception
from src.application.trainer_link import get_trainer_id_by_telegram_id
from src.application.training_group_series_notifications import notify_clients_group_series_schedule_updated
from src.application.training_group_use_cases import (
    TG_ACTIVE,
    TG_ARCHIVED,
    TG_DRAFT,
    TG_PAUSED,
    TG_RECRUITING,
    TrainingGroupReplaceBlockedError,
    TrainingGroupScheduleConflictError,
    _UNSET,
    add_group_member,
    approve_join_request,
    cancel_future_group_slots_in_range,
    cancel_group_slot,
    client_request_join_group,
    create_training_group,
    get_training_group_detail,
    list_open_training_groups_public,
    list_pending_join_requests,
    list_training_groups,
    list_upcoming_group_slots,
    reject_join_request,
    remove_group_member,
    replace_training_group_schedule,
    update_training_group,
)
from src.application.trainer_schedule_use_cases import trainer_offers_service
from src.application.subscription_tier_use_cases import trainer_has_groups_access
from src.application.client_use_cases import get_client_id_by_telegram_id, get_or_create_client_by_phone
from src.shared.config import Settings
from src.shared.telegram_webapp import InitDataAuthError, require_telegram_user_id
from src.shared.webapp_http_messages import (
    TRAINER_WEBAPP_FORBIDDEN_DETAIL,
    WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED,
)

router = APIRouter(tags=["webapp-training-groups"])


def _trainer_tid(init_data: str) -> int:
    try:
        return require_telegram_user_id(init_data, Settings().telegram_bot_token_trainer)
    except InitDataAuthError:
        raise miniapp_credential_http_exception() from None


def _client_tid(init_data: str) -> int:
    try:
        return require_telegram_user_id(init_data, Settings().telegram_bot_token_client)
    except InitDataAuthError:
        raise miniapp_credential_http_exception() from None


class ScheduleRuleIn(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., description="HH:MM")
    duration_minutes: int = Field(default=45, ge=15, le=480)


class CreateTrainingGroupBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    service_id: int
    arena_id: int | None = None
    max_members: int = Field(default=10, ge=2, le=500)
    status: str = Field(default=TG_RECRUITING)
    season_start_date: str | None = None
    catalog_visible: bool = True
    catalog_pitch: str | None = None
    schedule_rules: list[ScheduleRuleIn] = Field(min_length=1)


class PatchTrainingGroupBody(BaseModel):
    name: str | None = None
    max_members: int | None = Field(default=None, ge=2, le=500)
    status: str | None = None
    catalog_visible: bool | None = None
    catalog_pitch: str | None = None
    season_start_date: str | None = None


class AddMemberBody(BaseModel):
    """Either existing client_id, or phone + first_name to create/resolve client (same idea as schedule)."""

    client_id: int | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    expand_roster: bool = False


class ReplaceTrainingGroupScheduleBody(BaseModel):
    """Replace recurring rules; optional fields only when changing service/arena/season."""

    schedule_rules: list[ScheduleRuleIn] = Field(min_length=1)
    season_start_date: str | None = None
    service_id: int | None = None
    arena_id: int | None = None


class CancelGroupSlotsInRangeBody(BaseModel):
    date_from: str
    date_to: str


@router.get("/trainer/training-groups")
async def get_trainer_training_groups(
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    items = await list_training_groups(session, trainer_id)
    return {"groups": items}


@router.post("/trainer/training-groups")
async def post_trainer_training_groups(
    body: CreateTrainingGroupBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    if body.status not in (TG_DRAFT, TG_RECRUITING, TG_ACTIVE):
        raise HTTPException(status_code=400, detail="Invalid status")
    if not await trainer_offers_service(session, trainer_id, body.service_id):
        raise HTTPException(status_code=400, detail="Услуга не в вашем списке")
    if body.arena_id is not None:
        rchk = await session.execute(
            text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
            {"tid": trainer_id, "aid": body.arena_id},
        )
        if not rchk.fetchone():
            raise HTTPException(status_code=400, detail="Площадка не привязана к профилю")
    ssd: date | None = None
    if body.season_start_date:
        try:
            ssd = date.fromisoformat(body.season_start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid season_start_date")
    rules = [r.model_dump() for r in body.schedule_rules]
    try:
        gid = await create_training_group(
            session,
            trainer_id,
            name=body.name,
            service_id=body.service_id,
            arena_id=body.arena_id,
            max_members=body.max_members,
            status=body.status,
            season_start_date=ssd,
            catalog_visible=body.catalog_visible,
            catalog_pitch=body.catalog_pitch,
            schedule_rules=rules,
        )
    except TrainingGroupScheduleConflictError as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    return {"id": gid, "ok": True}


@router.get("/trainer/training-groups/{group_id:int}")
async def get_trainer_training_group_detail(
    group_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    d = await get_training_group_detail(session, trainer_id, group_id)
    if not d:
        raise HTTPException(status_code=404, detail="Not found")
    pending = await list_pending_join_requests(session, trainer_id, group_id)
    d["join_requests"] = pending
    return d


@router.get("/trainer/training-groups/{group_id:int}/upcoming-slots")
async def get_trainer_training_group_upcoming_slots(
    group_id: int,
    limit: int = Query(20, ge=1, le=100),
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    rows = await list_upcoming_group_slots(session, trainer_id, group_id, limit=limit)
    return {"slots": rows}


@router.put("/trainer/training-groups/{group_id:int}/schedule-rules")
async def put_trainer_training_group_schedule_rules(
    group_id: int,
    body: ReplaceTrainingGroupScheduleBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    rules = [r.model_dump() for r in body.schedule_rules]
    kwargs: dict = {"schedule_rules": rules}
    fs = body.model_fields_set
    if "season_start_date" in fs:
        if body.season_start_date in (None, ""):
            kwargs["season_start_date"] = None
        else:
            try:
                kwargs["season_start_date"] = date.fromisoformat(body.season_start_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid season_start_date") from None
    else:
        kwargs["season_start_date"] = _UNSET
    if "service_id" in fs:
        if body.service_id is None:
            raise HTTPException(status_code=400, detail="service_id cannot be null")
        if not await trainer_offers_service(session, trainer_id, int(body.service_id)):
            raise HTTPException(status_code=400, detail="Услуга не в вашем списке")
        kwargs["service_id"] = int(body.service_id)
    else:
        kwargs["service_id"] = _UNSET
    if "arena_id" in fs:
        aid = body.arena_id
        if aid is not None:
            rchk = await session.execute(
                text("SELECT 1 FROM trainer_arenas WHERE trainer_id = :tid AND arena_id = :aid"),
                {"tid": trainer_id, "aid": aid},
            )
            if not rchk.fetchone():
                raise HTTPException(status_code=400, detail="Площадка не привязана к профилю")
        kwargs["arena_id"] = aid
    else:
        kwargs["arena_id"] = _UNSET
    try:
        await replace_training_group_schedule(session, trainer_id, group_id, **kwargs)
    except TrainingGroupScheduleConflictError as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except TrainingGroupReplaceBlockedError as e:
        raise HTTPException(status_code=409, detail=e.message) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found") from None
    await notify_clients_group_series_schedule_updated(trainer_id, group_id)
    return {"ok": True}


@router.post("/trainer/training-groups/{group_id:int}/slots/{slot_id:int}/cancel")
async def post_cancel_training_group_slot(
    group_id: int,
    slot_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    ok = await cancel_group_slot(session, trainer_id, group_id, slot_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось отменить (нет слота или есть записи)")
    return {"ok": True}


@router.post("/trainer/training-groups/{group_id:int}/cancel-slots")
async def post_cancel_training_group_slots_in_range(
    group_id: int,
    body: CancelGroupSlotsInRangeBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    try:
        df = date.fromisoformat(body.date_from)
        dt = date.fromisoformat(body.date_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date_from / date_to") from None
    n = await cancel_future_group_slots_in_range(session, trainer_id, group_id, df, dt)
    return {"ok": True, "cancelled": n}


@router.patch("/trainer/training-groups/{group_id:int}")
async def patch_trainer_training_group(
    group_id: int,
    body: PatchTrainingGroupBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    if body.status is not None and body.status not in (
        TG_DRAFT,
        TG_RECRUITING,
        TG_ACTIVE,
        TG_PAUSED,
        TG_ARCHIVED,
    ):
        raise HTTPException(status_code=400, detail="Invalid status")
    ssd = None
    if body.season_start_date is not None:
        if body.season_start_date == "":
            ssd = None
        else:
            try:
                ssd = date.fromisoformat(body.season_start_date)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid season_start_date")
    ok = await update_training_group(
        session,
        trainer_id,
        group_id,
        name=body.name,
        max_members=body.max_members,
        status=body.status,
        catalog_visible=body.catalog_visible,
        catalog_pitch=body.catalog_pitch,
        season_start_date=ssd,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.post("/trainer/training-groups/{group_id:int}/members")
async def post_trainer_training_group_member(
    group_id: int,
    body: AddMemberBody,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    client_id: int
    if body.client_id is not None:
        client_id = int(body.client_id)
        r = await session.execute(text("SELECT 1 FROM clients WHERE id = :cid"), {"cid": client_id})
        if not r.fetchone():
            raise HTTPException(status_code=400, detail="Клиент не найден")
    elif body.phone and (body.first_name or "").strip():
        try:
            client_id = await get_or_create_client_by_phone(
                session,
                body.phone.strip(),
                first_name=(body.first_name or "").strip(),
                last_name=(body.last_name or "").strip() or None,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        raise HTTPException(
            status_code=400,
            detail="Укажите client_id или телефон и имя нового участника",
        )
    ok = await add_group_member(
        session, trainer_id, group_id, client_id, expand_roster=bool(body.expand_roster)
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось добавить (группа полна или архив)")
    return {"ok": True, "client_id": client_id}


@router.delete("/trainer/training-groups/{group_id:int}/members/{client_id:int}")
async def delete_trainer_training_group_member(
    group_id: int,
    client_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    ok = await remove_group_member(session, trainer_id, group_id, client_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.post("/trainer/training-groups/{group_id:int}/join-requests/{request_id:int}/approve")
async def post_approve_join_request(
    group_id: int,
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    ok = await approve_join_request(session, trainer_id, group_id, request_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось подтвердить")
    return {"ok": True}


@router.post("/trainer/training-groups/{group_id:int}/join-requests/{request_id:int}/reject")
async def post_reject_join_request(
    group_id: int,
    request_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    tid = _trainer_tid(raw)
    trainer_id = await get_trainer_id_by_telegram_id(session, tid)
    if not trainer_id:
        raise HTTPException(status_code=403, detail=TRAINER_WEBAPP_FORBIDDEN_DETAIL)
    if not await trainer_has_groups_access(session, trainer_id):
        raise HTTPException(status_code=403, detail=WEBAPP_DETAIL_SUBSCRIPTION_GROUPS_REQUIRED)
    ok = await reject_join_request(session, trainer_id, group_id, request_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Не удалось отклонить")
    return {"ok": True}


@router.post("/client/training-groups/{group_id:int}/join-request")
async def post_client_training_group_join_request(
    group_id: int,
    init_data: str | None = Query(None),
    x_telegram_init_data: str | None = Header(None, alias="X-Telegram-Init-Data"),
    session: AsyncSession = Depends(get_session),
):
    raw = init_data or x_telegram_init_data
    if not raw:
        raise miniapp_credential_http_exception()
    ctid = _client_tid(raw)
    client_id = await get_client_id_by_telegram_id(session, ctid)
    if not client_id:
        raise HTTPException(status_code=403, detail="Client profile required")
    ok, err = await client_request_join_group(session, group_id, client_id)
    if not ok:
        detail = {
            "not_found": "Группа не найдена",
            "not_recruiting": "Набор в эту группу закрыт",
            "full": "Нет свободных мест",
            "duplicate": "Вы уже в группе",
        }.get(err or "", "Невозможно вступить в группу")
        raise HTTPException(status_code=400, detail=detail)
    return {"ok": True}
