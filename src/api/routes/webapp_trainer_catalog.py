"""
Trainer Mini App: the «Каталог» section (TASK-140).

One GET for the whole screen, four POSTs for the four things a trainer can do to their card.
Every POST goes through ``trainer_catalog_state.set_catalog_state`` (directly or via
``trainer_use_cases``), so the journal and the notification can never disagree with the column.

Auth: Telegram initData validated with the trainer bot token; ``trainer_id`` always comes from
it, never from the body. Available in every account status — a trainer deciding whether to be
listed is exactly the person who has not been activated yet.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_session
from src.api.miniapp_auth import MiniAppPrincipal, get_trainer_miniapp_principal
from src.application.trainer_catalog_state import (
    CATALOG_ACTOR_TRAINER,
    REASON_TRAINER_CANCELLED,
    REASON_TRAINER_HIDDEN,
    REASON_TRAINER_RESTORED,
    CatalogStateError,
    set_catalog_state,
)
from src.application.trainer_catalog_view import build_catalog_screen_payload
from src.application.trainer_link import get_trainer_id_linked_any_status_from_principal
from src.application.trainer_profile_pending import trainer_has_pending_text_revision
from src.application.trainer_use_cases import (
    discard_active_trainer_text_revision_with_feedback,
    get_trainer,
    reconcile_catalog_state_for_card,
    try_submit_trainer_for_moderation_review,
)
from src.shared.audit import ACTOR_API, audit_log
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _trainer_or_403(session: AsyncSession, principal: MiniAppPrincipal) -> dict:
    trainer_id = await get_trainer_id_linked_any_status_from_principal(session, principal)
    if not trainer_id:
        raise HTTPException(status_code=403, detail="Telegram not linked to a trainer")
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found")
    return trainer


async def _acting_trainer(session: AsyncSession, principal: MiniAppPrincipal) -> dict:
    """
    Same as above, but refuses when the studio owns publication.

    A studio-managed trainer (``studio_access_mode = admin_only``) sees the section read-only:
    state and history are theirs to know, the decision is not theirs to make.
    """
    trainer = await _trainer_or_403(session, principal)
    payload = await build_catalog_screen_payload(session, trainer)
    if not payload.get("can_act"):
        raise HTTPException(status_code=403, detail="Публикацией карточки управляет студия")
    return trainer


@router.get("/trainer/catalog")
async def get_trainer_catalog_screen(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """State, preview, pending revision, readiness, warnings, metrics and history in one call."""
    trainer = await _trainer_or_403(session, principal)
    return await build_catalog_screen_payload(session, trainer)


@router.post("/trainer/catalog/submit")
async def submit_trainer_catalog_card(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """
    «Отправить на проверку» — the one deliberate act of publication.

    Deliberate is the point: publication used to be a side effect of saving a complete profile,
    so trainers polishing a card for their own students ended up in the public catalog without
    ever being asked. 422 carries the missing fields so the screen can open the carousel on
    exactly those.
    """
    trainer = await _acting_trainer(session, principal)
    trainer_id = int(trainer["id"])
    result = await try_submit_trainer_for_moderation_review(
        session, trainer_id, requested_by_trainer=True
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result)
    audit_log("trainer.catalog_submitted", ACTOR_API, "webapp_trainer_catalog", {"trainer_id": trainer_id})
    fresh = await get_trainer(session, trainer_id)
    return await build_catalog_screen_payload(session, fresh)


@router.post("/trainer/catalog/hide")
async def hide_trainer_catalog_card(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """
    «Снять с публикации». Reversible in one tap and without a second review — the dialog in the
    UI says so, and ``restore`` below is what makes it true.
    """
    trainer = await _acting_trainer(session, principal)
    trainer_id = int(trainer["id"])
    state = (trainer.get("catalog_state") or CATALOG_STATE_DRAFT).strip()
    if state != CATALOG_STATE_PUBLISHED:
        raise HTTPException(status_code=409, detail="Карточка сейчас не опубликована")
    await set_catalog_state(
        session,
        trainer_id,
        CATALOG_STATE_HIDDEN,
        reason=REASON_TRAINER_HIDDEN,
        actor_type=CATALOG_ACTOR_TRAINER,
        actor_id=trainer_id,
    )
    audit_log("trainer.catalog_hidden", ACTOR_API, "webapp_trainer_catalog", {"trainer_id": trainer_id})
    fresh = await get_trainer(session, trainer_id)
    return await build_catalog_screen_payload(session, fresh)


@router.post("/trainer/catalog/restore")
async def restore_trainer_catalog_card(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """
    «Вернуть в каталог» — from ``hidden`` straight back, from ``paused`` once the gap is filled.

    A ``paused`` card with the gap still open returns 422 with the missing fields rather than a
    refusal: the screen turns that into the carousel, which is the actual way back.
    """
    trainer = await _acting_trainer(session, principal)
    trainer_id = int(trainer["id"])
    state = (trainer.get("catalog_state") or CATALOG_STATE_DRAFT).strip()

    if state == CATALOG_STATE_HIDDEN:
        await set_catalog_state(
            session,
            trainer_id,
            CATALOG_STATE_PUBLISHED,
            reason=REASON_TRAINER_RESTORED,
            actor_type=CATALOG_ACTOR_TRAINER,
            actor_id=trainer_id,
        )
    elif state == CATALOG_STATE_PAUSED:
        changed = await reconcile_catalog_state_for_card(session, trainer_id)
        if not changed:
            fresh = await get_trainer(session, trainer_id)
            payload = await build_catalog_screen_payload(session, fresh)
            raise HTTPException(status_code=422, detail=payload["readiness"])
    else:
        raise HTTPException(status_code=409, detail="Карточку сейчас нельзя вернуть")

    audit_log("trainer.catalog_restored", ACTOR_API, "webapp_trainer_catalog", {"trainer_id": trainer_id})
    fresh = await get_trainer(session, trainer_id)
    return await build_catalog_screen_payload(session, fresh)


@router.post("/trainer/catalog/withdraw")
async def withdraw_trainer_catalog_request(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """«Отменить заявку» while it is still in the queue — back to a draft, stamp cleared."""
    trainer = await _acting_trainer(session, principal)
    trainer_id = int(trainer["id"])
    state = (trainer.get("catalog_state") or CATALOG_STATE_DRAFT).strip()
    if state != CATALOG_STATE_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Заявки на проверке нет")
    from src.infrastructure.repositories.trainer_repository import TrainerRepository

    await set_catalog_state(
        session,
        trainer_id,
        CATALOG_STATE_DRAFT,
        reason=REASON_TRAINER_CANCELLED,
        actor_type=CATALOG_ACTOR_TRAINER,
        actor_id=trainer_id,
    )
    await TrainerRepository(session).clear_moderation_submitted_at(trainer_id)
    await session.commit()
    audit_log("trainer.catalog_withdrawn", ACTOR_API, "webapp_trainer_catalog", {"trainer_id": trainer_id})
    fresh = await get_trainer(session, trainer_id)
    return await build_catalog_screen_payload(session, fresh)


@router.post("/trainer/catalog/cancel-revision")
async def cancel_trainer_catalog_revision(
    session: AsyncSession = Depends(get_session),
    principal: MiniAppPrincipal = Depends(get_trainer_miniapp_principal),
) -> dict:
    """
    Drop a pending text/photo edit and keep the published card as it is.

    The server side already existed — only a moderator could reach it. The trainer who made the
    edit had no way to take it back, which is odd for a change only they can see the point of.
    """
    trainer = await _acting_trainer(session, principal)
    trainer_id = int(trainer["id"])
    if not (trainer_has_pending_text_revision(trainer) or trainer.get("photo_pending")):
        raise HTTPException(status_code=409, detail="Правок на проверке нет")
    await discard_active_trainer_text_revision_with_feedback(session, trainer_id, None)
    audit_log(
        "trainer.catalog_revision_cancelled",
        ACTOR_API,
        "webapp_trainer_catalog",
        {"trainer_id": trainer_id},
    )
    fresh = await get_trainer(session, trainer_id)
    return await build_catalog_screen_payload(session, fresh)
