"""
Everything the «Каталог» screen shows, assembled in one place (TASK-140).

The screen answers four questions and nothing else: am I in the catalog, why not, what do
clients see, and what happened to my card. So this module returns one payload with

* ``state`` — one of six, plus the reason code and the human sentence from the journal;
* ``preview`` — the card as a client sees it, so «опубликуется что-то кривое» stops being a fear;
* ``revision`` — both versions when a text/photo edit is waiting for a moderator; before this,
  a trainer uploaded a photo and had no way to tell clients were still seeing the old one;
* ``readiness`` — what is still missing, in the same words the profile carousel uses;
* ``warnings`` — things that hurt discoverability without unpublishing the card (a card with no
  public arenas stays in the list but falls out of every arena filter — the old UI insisted
  everything was fine);
* ``metrics`` — the counters that already exist, not new ones;
* ``events`` — the history, which is what makes the whole thing auditable by the trainer.

Read-only: every state change goes through ``trainer_catalog_state.set_catalog_state``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_use_cases import (
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    get_effective_studio_access_mode,
    list_active_collective_memberships,
)
from src.application.demand_signals_use_cases import get_signals_since
from src.application.trainer_catalog_state import list_catalog_events
from src.application.trainer_profile_completeness import (
    analyze_moderation_profile_completeness,
    analyze_moderation_submission_readiness,
    missing_labels_ru,
)
from src.application.trainer_profile_pending import (
    trainer_has_photo_pending_revision,
    trainer_has_pending_text_revision,
)
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
)

logger = logging.getLogger(__name__)

METRICS_WINDOW_DAYS = 7
EVENTS_LIMIT = 20

# One sentence per state. Kept server-side so the push, the digest and the screen cannot drift
# into describing the same state three different ways.
STATE_HEADLINE_RU: dict[str, str] = {
    CATALOG_STATE_DRAFT: "Вас пока нет в каталоге",
    CATALOG_STATE_PENDING_REVIEW: "На проверке",
    CATALOG_STATE_PUBLISHED: "В каталоге",
    CATALOG_STATE_HIDDEN: "Снято вами",
    CATALOG_STATE_PAUSED: "Приостановлено",
    CATALOG_STATE_NEEDS_REVISION: "Модератор попросил поправить",
}

STATE_BODY_RU: dict[str, str] = {
    CATALOG_STATE_DRAFT: (
        "Каталог — список тренеров, который смотрят новые ученики. Сейчас к вам приходят "
        "только по вашей ссылке, и это нормально."
    ),
    CATALOG_STATE_PENDING_REVIEW: (
        "Обычно отвечаем в течение рабочего дня — пуш придёт сразу. Карточку можно дополнять, "
        "заявка не сбросится."
    ),
    CATALOG_STATE_PUBLISHED: "Клиенты находят вас в общем списке.",
    CATALOG_STATE_HIDDEN: (
        "Запись по вашей ссылке работает как обычно. Вернём сразу, без повторной проверки."
    ),
    CATALOG_STATE_PAUSED: (
        "Это не связано с подпиской и не влияет на ваши записи. Заполните — и карточка "
        "вернётся сама, без проверки."
    ),
    CATALOG_STATE_NEEDS_REVISION: "Исправьте и отправьте снова — проверим ещё раз.",
}

# Shown in every state: the fear of «не заплатил — пропал» costs more than the sentence does.
SUBSCRIPTION_NOTE_RU = (
    "Подписка на каталог не влияет: если она закончится, карточка останется — отключится "
    "только самозапись."
)


def _state_actions(state: str, *, can_act: bool, submit_ready: bool) -> list[str]:
    """Which buttons the screen may offer. The trainer's own state, not a permission model."""
    if not can_act:
        return []
    if state == CATALOG_STATE_PUBLISHED:
        return ["hide"]
    if state in (CATALOG_STATE_HIDDEN, CATALOG_STATE_PAUSED):
        return ["restore"]
    if state == CATALOG_STATE_PENDING_REVIEW:
        return ["withdraw"]
    # draft / needs_revision: publishing is the one deliberate act, and only when ready.
    return ["submit"] if submit_ready else ["fill"]


async def _preview(session: AsyncSession, trainer: dict[str, Any]) -> dict[str, Any]:
    """The card as the catalog list renders it — same fields, no internal state."""
    profile = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    arena_public = trainer.get("arena_is_public") or {}
    public_arena_ids = [aid for aid, is_pub in arena_public.items() if is_pub]
    city_name = None
    if profile.get("city_id") is not None:
        r = await session.execute(
            text("SELECT name FROM cities WHERE id = :cid"), {"cid": profile.get("city_id")}
        )
        row = r.fetchone()
        city_name = row[0] if row else None
    prices = [
        int(s["price_cents"])
        for s in (trainer.get("services") or [])
        if isinstance(s, dict) and s.get("price_cents") is not None
    ]
    photos = trainer.get("photos") or []
    return {
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "city_name": city_name,
        "photo_file_key": (photos[0] or {}).get("file_key") if photos else None,
        "public_arena_count": len(public_arena_ids),
        "arena_names": trainer.get("arena_names") or [],
        "price_from_cents": min(prices) if prices else None,
        "rating_avg": profile.get("rating_avg"),
        "rating_count": profile.get("rating_count"),
    }


def _revision(trainer: dict[str, Any]) -> dict[str, Any] | None:
    """
    Both versions of the card while a moderated edit waits.

    ``profile_pending`` / ``photo_pending`` already existed; what was missing was ever telling
    the trainer that clients are still looking at the previous values.
    """
    has_text = trainer_has_pending_text_revision(trainer)
    has_photo = trainer_has_photo_pending_revision(trainer)
    if not has_text and not has_photo:
        return None
    published = trainer.get("profile") if isinstance(trainer.get("profile"), dict) else {}
    pending = trainer.get("profile_pending") if isinstance(trainer.get("profile_pending"), dict) else {}
    photo_pending = trainer.get("photo_pending") if isinstance(trainer.get("photo_pending"), dict) else {}
    photos = trainer.get("photos") or []
    return {
        "has_text": has_text,
        "has_photo": has_photo,
        "current": {
            "first_name": published.get("first_name"),
            "last_name": published.get("last_name"),
            "description": published.get("description"),
            "photo_file_key": (photos[0] or {}).get("file_key") if photos else None,
        },
        "next": {
            "first_name": pending.get("first_name", published.get("first_name")),
            "last_name": pending.get("last_name", published.get("last_name")),
            "description": pending.get("description", published.get("description")),
            "photo_file_key": photo_pending.get("file_key")
            or ((photos[0] or {}).get("file_key") if photos else None),
        },
    }


def _warnings(trainer: dict[str, Any], state: str) -> list[dict[str, str]]:
    """
    Soft problems: they cost discoverability but must not take the card down.

    Hiding every arena is the one that used to lie outright — the profile toggle said «клиенты
    находят вас в общем списке» at the exact moment the trainer dropped out of every arena
    filter and of the arena-derived city rows in ``trainer_cities``.
    """
    if state != CATALOG_STATE_PUBLISHED:
        return []
    out: list[dict[str, str]] = []
    arena_public = trainer.get("arena_is_public") or {}
    if arena_public and not any(arena_public.values()):
        out.append(
            {
                "code": "no_public_arenas",
                "text": "Ни одной открытой площадки — вас не найдут по фильтру «арена».",
                "action": "arenas",
            }
        )
    _, full_missing = analyze_moderation_profile_completeness(trainer)
    soft = [k for k in full_missing if k in ("description", "education", "experience_years")]
    for key in soft:
        label = missing_labels_ru([key])
        if label:
            out.append(
                {
                    "code": f"soft_{key}",
                    "text": f"Не заполнено: {label[0]} — карточка выглядит скромнее соседних.",
                    "action": "profile",
                }
            )
    return out


async def build_catalog_screen_payload(
    session: AsyncSession, trainer: dict[str, Any]
) -> dict[str, Any]:
    """One GET for the whole screen. ``trainer`` is a ``get_trainer`` aggregate."""
    trainer_id = int(trainer["id"])
    state = (trainer.get("catalog_state") or CATALOG_STATE_DRAFT).strip()
    submit_ready, missing = analyze_moderation_submission_readiness(trainer)

    studio_mode = await get_effective_studio_access_mode(session, trainer_id)
    managed_by_studio = studio_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY
    studio_name = None
    if managed_by_studio:
        memberships = await list_active_collective_memberships(session, trainer_id)
        if memberships:
            studio_name = getattr(memberships[0], "display_name", None)

    events = await list_catalog_events(session, trainer_id, limit=EVENTS_LIMIT)
    # The sentence for the current state comes from the event that produced it, not from a
    # separate copy that could describe a different state than the column holds.
    reason_detail = events[0]["reason_detail"] if events else None

    since = datetime.now(timezone.utc) - timedelta(days=METRICS_WINDOW_DAYS)
    try:
        recap = await get_signals_since(session, trainer_id=trainer_id, since=since)
        metrics = {
            "window_days": METRICS_WINDOW_DAYS,
            "profile_views": recap.profile_views,
            "contact_clicks": recap.contact_clicks,
            "catalog_favorites": recap.catalog_favorites,
        }
    except Exception:  # noqa: BLE001 — metrics are decoration; the state is the point
        logger.exception("catalog screen metrics failed trainer_id=%s", trainer_id)
        metrics = None

    _, full_missing = analyze_moderation_profile_completeness(trainer)
    return {
        "state": state,
        "state_reason": trainer.get("catalog_state_reason"),
        "state_detail": reason_detail,
        "state_changed_at": trainer.get("catalog_state_changed_at"),
        "headline": STATE_HEADLINE_RU.get(state, ""),
        "body": STATE_BODY_RU.get(state, ""),
        "subscription_note": SUBSCRIPTION_NOTE_RU,
        "can_act": not managed_by_studio,
        "managed_by_studio": managed_by_studio,
        "studio_name": studio_name,
        "actions": _state_actions(state, can_act=not managed_by_studio, submit_ready=submit_ready),
        "readiness": {
            "submit_ready": submit_ready,
            "missing_fields": missing,
            "missing_labels_ru": missing_labels_ru(missing, first_name_only=True),
            "optional_missing_labels_ru": missing_labels_ru(
                [k for k in full_missing if k in ("description", "education", "experience_years")]
            ),
        },
        "preview": await _preview(session, trainer),
        "revision": _revision(trainer),
        "warnings": _warnings(trainer, state),
        "metrics": metrics,
        "events": [
            {
                "from_state": e["from_state"],
                "to_state": e["to_state"],
                "reason": e["reason"],
                "reason_detail": e["reason_detail"],
                "actor_type": e["actor_type"],
                "created_at": e["created_at"],
                "headline": STATE_HEADLINE_RU.get((e["to_state"] or "").strip(), e["to_state"]),
            }
            for e in events
        ],
    }
