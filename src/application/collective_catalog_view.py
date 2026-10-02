"""
Everything the org «Каталог» screen shows, assembled in one place (TASK-141 S5).

Parallel to ``trainer_catalog_view.build_catalog_screen_payload``, scaled down to what a
school actually has: no moderator queue (owner decision), no photos/arenas/services/ratings
infra for collectives yet, so no metrics and no revision diff. The preview card shows exactly
the fields ``update_org_collective_profile_for_operator`` writes — the same facts, not a
lookalike — because that's the whole of what a school's public landing page
(``GET /api/public/collectives/{slug}``) has to show today.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.collective_catalog_state import (
    COLLECTIVE_CATALOG_STATE_DRAFT,
    COLLECTIVE_CATALOG_STATE_HIDDEN,
    COLLECTIVE_CATALOG_STATE_PUBLISHED,
    REASON_BACKFILL_0209,
    get_collective_catalog_state,
    list_collective_catalog_events,
)
from src.application.collective_use_cases import (
    get_org_collective_profile_payload,
    org_profile_readiness,
)

EVENTS_LIMIT = 20

STATE_HEADLINE_RU: dict[str, str] = {
    COLLECTIVE_CATALOG_STATE_DRAFT: "Вас пока нет в каталоге",
    COLLECTIVE_CATALOG_STATE_PUBLISHED: "В каталоге",
    COLLECTIVE_CATALOG_STATE_HIDDEN: "Снято вами",
}

STATE_BODY_RU: dict[str, str] = {
    COLLECTIVE_CATALOG_STATE_DRAFT: (
        "Заполните обязательные поля профиля — и школа появится на своей публичной странице."
    ),
    COLLECTIVE_CATALOG_STATE_PUBLISHED: "Страница школы открыта по ссылке.",
    COLLECTIVE_CATALOG_STATE_HIDDEN: (
        "Страница временно скрыта. Вернём сразу, как только снова нажмёте «Опубликовать»."
    ),
}

_EVENT_HEADLINE_RU: dict[str, str] = {
    COLLECTIVE_CATALOG_STATE_PUBLISHED: "Вы опубликовали школу в каталоге",
    COLLECTIVE_CATALOG_STATE_HIDDEN: "Вы сняли школу с публикации",
}


def event_headline_ru(to_state: str | None, reason: str | None) -> str:
    if reason == REASON_BACKFILL_0209:
        return "Состояние перенесено при запуске раздела"
    return _EVENT_HEADLINE_RU.get(to_state or "", "Состояние изменилось")


async def build_collective_catalog_screen_payload(
    session: AsyncSession, collective_id: int
) -> dict[str, Any] | None:
    """One GET for the whole screen."""
    state_row = await get_collective_catalog_state(session, collective_id)
    if state_row is None:
        return None
    profile = await get_org_collective_profile_payload(session, collective_id)
    if profile is None:
        return None

    state = state_row["catalog_state"]
    readiness = profile["readiness"]
    events = await list_collective_catalog_events(session, collective_id, limit=EVENTS_LIMIT)

    contacts = profile.get("contacts") or {}
    preview = {
        "display_name": profile.get("display_name"),
        "about": profile.get("about"),
        "phone": contacts.get("phone"),
        "telegram": contacts.get("telegram"),
        "logo_url": profile.get("logo_url"),
    }

    public_url = None
    slug = profile.get("slug")
    if state == COLLECTIVE_CATALOG_STATE_PUBLISHED and slug:
        public_url = f"/api/public/collectives/{slug}"

    return {
        "collective_id": collective_id,
        "slug": slug,
        "state": state,
        "headline": STATE_HEADLINE_RU.get(state, ""),
        "body": STATE_BODY_RU.get(state, ""),
        "can_publish": state in (COLLECTIVE_CATALOG_STATE_DRAFT, COLLECTIVE_CATALOG_STATE_HIDDEN)
        and readiness["ready"],
        "can_hide": state == COLLECTIVE_CATALOG_STATE_PUBLISHED,
        "readiness": readiness,
        "preview": preview,
        "public_url": public_url,
        "events": [
            {
                "headline": event_headline_ru(e["to_state"], e["reason"]),
                "created_at": e["created_at"].isoformat() if e["created_at"] else None,
            }
            for e in events
        ],
    }
