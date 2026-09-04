"""Client ↔ trainer edges: bookmarks, primary trainer, slot-wait subscriptions."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, client_catalog_telegram_key, get_client_miniapp_principal
from src.api.routes.public import (
    _trainer_public_catalog_exposed,
    assemble_trainer_catalog_payload,
)
from src.api.routes.webapp_client_payloads import client_bookings_days_payload
from src.application.client_profile_use_cases import resolve_acting_client_id
from src.application.client_trainer_primary_graph import (
    compute_primary_edge,
    edge_json_with_trainer_hints,
    next_booking_per_trainer,
    serialize_trainer_edge_row,
)
from src.application.booking_use_cases import client_latest_booking_primary_candidate
from src.application.client_session_use_cases import get_session as read_client_bot_session
from src.application.client_trainer_edge_use_cases import (
    get_all_edges as get_all_trainer_edges,
    get_edge as get_client_trainer_edge,
    get_primary_edge,
    save_trainer as uc_save_trainer,
    set_primary_trainer as uc_set_primary_trainer,
    subscribe_notify_slots as uc_subscribe_notify_slots,
    trainer_display_hints_by_ids,
    unset_primary_trainer as uc_unset_primary_trainer,
    unsave_trainer as uc_unsave_trainer,
    unsubscribe_notify_slots as uc_unsubscribe_notify_slots,
)
from src.application.trainer_use_cases import get_trainer
from src.application.trainer_client_favorite_notify import notify_trainer_new_catalog_favorite
from src.infrastructure.db.session import async_session_factory


def _parse_profile_id_header(x_profile_id: str | None) -> int | None:
    """Malformed/stale header degrades to the account's own profile — never a 422."""
    if not x_profile_id:
        return None
    try:
        return int(x_profile_id)
    except ValueError:
        return None

router = APIRouter(tags=["webapp"])

logger = logging.getLogger(__name__)


async def _client_may_open_trainer_deep_link(
    session: AsyncSession,
    catalog_telegram_id: int,
    trainer_id: int,
    client_id: int | None,
) -> bool:
    """True when client may open a trainer card outside public catalog (edge, booking, or invite session)."""
    edge = await get_client_trainer_edge(client_id, trainer_id, session) if client_id is not None else None
    if edge is not None:
        return True
    sess = await read_client_bot_session(catalog_telegram_id, session)
    sess_tid = (sess or {}).get("selected_trainer_id")
    if sess_tid is not None and int(sess_tid) == int(trainer_id):
        return True
    r = await session.execute(
        text(
            """
            SELECT 1
            FROM bookings b
            INNER JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            WHERE c.telegram_id = :tg
              AND b.trainer_id = :tid
              AND b.status IN ('pending', 'confirmed', 'completed', 'no_show')
              AND COALESCE(TRIM(LOWER(COALESCE(s.status, ''))), '') <> 'cancelled'
            LIMIT 1
            """
        ),
        {"tg": catalog_telegram_id, "tid": trainer_id},
    )
    return r.fetchone() is not None


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


@router.get("/client/catalog-trainer/{trainer_id:int}")
async def get_client_catalog_trainer_card(
    trainer_id: int,
    request: Request,
    response: Response,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """
    Same payload as GET /api/public/trainers/{id} but allows hidden/disabled catalog trainers when the
    client already has a relationship (edge or booking). Fixes hub → catalog deep links that 404 on public API.
    """
    response.headers["Cache-Control"] = "no-store"
    catalog_tid = client_catalog_telegram_key(principal)
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    if not _trainer_public_catalog_exposed(trainer):
        client_id = await resolve_acting_client_id(session, catalog_tid, _parse_profile_id_header(x_profile_id))
        allowed = await _client_may_open_trainer_deep_link(session, catalog_tid, trainer_id, client_id)
        if not allowed:
            raise HTTPException(status_code=404, detail="Trainer not found")
    return await assemble_trainer_catalog_payload(
        session=session, trainer_id=trainer_id, trainer=trainer, request=request
    )


@router.get("/client/trainer-edges")
async def get_client_trainer_edges(
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """All client ↔ trainer edges + display hints + next upcoming booking per trainer."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await resolve_acting_client_id(session, catalog_tid, _parse_profile_id_header(x_profile_id))
    edges = await get_all_trainer_edges(client_id, session) if client_id is not None else []
    booking_tid, booking_svc = await client_latest_booking_primary_candidate(session, catalog_tid)

    sess_row = await read_client_bot_session(catalog_tid, session)
    session_trainer_id = int(sess_row["selected_trainer_id"]) if (sess_row or {}).get("selected_trainer_id") else None
    explicit_primary = await get_primary_edge(client_id, session) if client_id is not None else None

    primary = compute_primary_edge(
        edges,
        session_trainer_id,
        booking_primary_trainer_id=booking_tid,
        booking_primary_service_id=booking_svc,
        explicit_primary_edge=explicit_primary,
    )
    primary_tid = int(primary["trainer_id"]) if primary else None

    hint_ids = sorted({int(e["trainer_id"]) for e in edges} | ({primary_tid} if primary_tid else set()))
    hints = await trainer_display_hints_by_ids(session, hint_ids)

    bookings_payload = await client_bookings_days_payload(session, catalog_tid)
    saved = [e for e in edges if e.get("is_saved") and int(e["trainer_id"]) != primary_tid]
    past = [
        e for e in edges
        if e.get("completed_count", 0) > 0
        and not e.get("is_saved")
        and int(e["trainer_id"]) != primary_tid
    ]
    next_per_trainer = next_booking_per_trainer(bookings_payload.get("days") or [])
    return {
        "primary": edge_json_with_trainer_hints(primary, hints, next_per_trainer) if primary else None,
        "saved": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in saved],
        "past": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in past],
        "all": [edge_json_with_trainer_hints(e, hints, next_per_trainer) for e in edges],
    }


async def _resolve_edge_client_id_or_400(
    session: AsyncSession, catalog_tid: int, x_profile_id: str | None
) -> int:
    """
    Edge rows are keyed by client_id now (EPIC1 Slice 5) — a trainer-edge write needs a real
    ``clients`` row to attach to. Pre-registration accounts (no client row yet) get a clear
    400 instead of silently writing an edge no read path could ever find again.
    """
    client_id = await resolve_acting_client_id(session, catalog_tid, _parse_profile_id_header(x_profile_id))
    if client_id is None:
        raise HTTPException(status_code=400, detail="Сначала завершите регистрацию.")
    return int(client_id)


@router.post("/client/trainer-edges/save")
async def post_client_save_trainer(
    body: TrainerEdgeSaveBody,
    background_tasks: BackgroundTasks,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Bookmark a trainer (is_saved = true). Idempotent. Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
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
        client_id, catalog_tid, body.trainer_id, session, catalog_service_id=svc_id
    )
    if became_saved:
        background_tasks.add_task(_bg_notify_trainer_catalog_favorite, body.trainer_id, catalog_tid)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/save/{trainer_id:int}")
async def delete_client_save_trainer(
    trainer_id: int,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Remove bookmark (is_saved = false). Idempotent. Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    edge = await uc_unsave_trainer(client_id, catalog_tid, trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.post("/client/trainer-edges/primary")
async def post_client_set_primary_trainer(
    body: TrainerEdgePrimaryBody,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Set primary trainer (is_primary = true). Demotes previous primary. Syncs legacy session field."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    edge = await uc_set_primary_trainer(client_id, catalog_tid, body.trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/primary")
async def delete_client_primary_trainer(
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Clear primary designation (no trainer is 'main' now). Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    await uc_unset_primary_trainer(client_id, catalog_tid, session)
    return {"success": True}


@router.post("/client/trainer-edges/notify-slots")
async def post_client_notify_slots(
    body: TrainerEdgeNotifyBody,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Subscribe to slot-availability notification for a trainer. Idempotent. Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    edge = await uc_subscribe_notify_slots(client_id, catalog_tid, body.trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}


@router.delete("/client/trainer-edges/notify-slots/{trainer_id:int}")
async def delete_client_notify_slots(
    trainer_id: int,
    x_profile_id: str | None = Header(None),
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_client_miniapp_principal),
):
    """Cancel slot-availability subscription. Idempotent. Auth: client initData."""
    catalog_tid = client_catalog_telegram_key(principal)
    client_id = await _resolve_edge_client_id_or_400(session, catalog_tid, x_profile_id)
    edge = await uc_unsubscribe_notify_slots(client_id, catalog_tid, trainer_id, session)
    return {"edge": serialize_trainer_edge_row(edge)}
