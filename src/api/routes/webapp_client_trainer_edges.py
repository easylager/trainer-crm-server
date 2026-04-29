"""Client ↔ trainer edges: bookmarks, primary trainer, slot-wait subscriptions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.webapp_client_payloads import client_bookings_days_payload
from src.api.routes.webapp_client_trainer_graph import (
    compute_primary_edge,
    edge_json_with_trainer_hints,
    next_booking_per_trainer,
    serialize_trainer_edge_row,
)
from src.application.client_session_use_cases import get_session as read_client_bot_session
from src.application.client_trainer_edge_use_cases import (
    get_all_edges as get_all_trainer_edges,
    save_trainer as uc_save_trainer,
    set_primary_trainer as uc_set_primary_trainer,
    subscribe_notify_slots as uc_subscribe_notify_slots,
    trainer_display_hints_by_ids,
    unset_primary_trainer as uc_unset_primary_trainer,
    unsave_trainer as uc_unsave_trainer,
    unsubscribe_notify_slots as uc_unsubscribe_notify_slots,
)
from src.application.trainer_client_favorite_notify import notify_trainer_new_catalog_favorite
from src.infrastructure.db.session import async_session_factory

router = APIRouter(tags=["webapp"])

logger = logging.getLogger(__name__)


async def _bg_notify_trainer_catalog_favorite(trainer_id: int, client_catalog_telegram_id: int) -> None:
    try:
        async with async_session_factory() as s:
            await notify_trainer_new_catalog_favorite(
                session=s,
                trainer_id=trainer_id,
                client_catalog_telegram_id=client_catalog_telegram_id,
            )
    except Exception:
        logger.exception(
            "background catalog-favorite notify failed trainer_id=%s",
            trainer_id,
        )


class TrainerEdgeSaveBody(BaseModel):
    trainer_id: int
    catalog_service_id: int | None = None


class TrainerEdgePrimaryBody(BaseModel):
    trainer_id: int


class TrainerEdgeNotifyBody(BaseModel):
    trainer_id: int


@router.get("/client/trainer-edges")
async def get_client_trainer_edges(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """All client ↔ trainer edges + display hints + next upcoming booking per trainer."""
    catalog_tid = client_catalog_telegram_key(principal)
    edges = await get_all_trainer_edges(catalog_tid, session)
    hints = await trainer_display_hints_by_ids(session, [int(e["trainer_id"]) for e in edges])
    bookings_payload = await client_bookings_days_payload(session, catalog_tid)
    next_per_trainer = next_booking_per_trainer(bookings_payload.get("days") or [])

    sess_row = await read_client_bot_session(catalog_tid, session)
    session_trainer_id = int(sess_row["selected_trainer_id"]) if (sess_row or {}).get("selected_trainer_id") else None

    primary = compute_primary_edge(edges, session_trainer_id)
    primary_tid = int(primary["trainer_id"]) if primary else None

    saved = [e for e in edges if e.get("is_saved") and int(e["trainer_id"]) != primary_tid]
    past = [
        e for e in edges
        if e.get("completed_count", 0) > 0
        and not e.get("is_saved")
        and int(e["trainer_id"]) != primary_tid
    ]
    return {
        "primary": edge_json_with_trainer_hints(primary, hints, next_per_trainer) if primary else None,
        "saved": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in saved],
        "past": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in past],
        "all": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in edges],
    }


@router.post("/client/trainer-edges/save")
async def post_client_save_trainer(
    body: TrainerEdgeSaveBody,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Bookmark a trainer (is_saved = true). Idempotent. Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    svc_id = body.catalog_service_id
    if svc_id is None:
        sess_row = await read_client_bot_session(catalog_tid, session)
        stid = (sess_row or {}).get("selected_trainer_id")
        if stid is not None and int(stid) == int(body.trainer_id):
            raw = (sess_row or {}).get("selected_service_id")
            if raw is not None:
                try:
                    svc_id = int(raw)
                except (TypeError, ValueError):
                    svc_id = None
    edge, became_saved = await uc_save_trainer(
        catalog_tid, body.trainer_id, session, catalog_service_id=svc_id
    )
    if became_saved:
        background_tasks.add_task(_bg_notify_trainer_catalog_favorite, body.trainer_id, catalog_tid)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/save/{trainer_id:int}")
async def delete_client_save_trainer(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Remove bookmark (is_saved = false). Idempotent. Auth: client initData."""
    edge = await uc_unsave_trainer(client_catalog_telegram_key(principal), trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.post("/client/trainer-edges/primary")
async def post_client_set_primary_trainer(
    body: TrainerEdgePrimaryBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Set primary trainer (is_primary = true). Demotes previous primary. Syncs legacy session field."""
    edge = await uc_set_primary_trainer(client_catalog_telegram_key(principal), body.trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/primary")
async def delete_client_primary_trainer(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Clear primary designation (no trainer is 'main' now). Auth: client initData."""
    await uc_unset_primary_trainer(client_catalog_telegram_key(principal), session)
    return {"success": True}


@router.post("/client/trainer-edges/notify-slots")
async def post_client_notify_slots(
    body: TrainerEdgeNotifyBody,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Subscribe to slot-availability notification for a trainer. Idempotent. Auth: client initData."""
    edge = await uc_subscribe_notify_slots(client_catalog_telegram_key(principal), body.trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/notify-slots/{trainer_id:int}")
async def delete_client_notify_slots(
    trainer_id: int,
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Cancel slot-availability subscription. Idempotent. Auth: client initData."""
    edge = await uc_unsubscribe_notify_slots(client_catalog_telegram_key(principal), trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}
