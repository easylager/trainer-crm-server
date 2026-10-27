"""Admin «Путь тренеров»: how far each trainer got, newest first, so an admin knows who to message.

Seven milestones, computed from real rows (never from ``trainers.status`` — ``active`` means
catalog-published, not working):

1. entered the bot (``telegram_id`` linked)
2. profile: first name + city
3. services + a place to work (arena, or a declared online/outdoor format)
4. schedule: a weekly template or at least one slot
5. copied the client invite link
6. first client (roster entry or non-sandbox booking)
7. first real booking
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_profile_completeness import analyze_moderation_submission_readiness
from src.application.trainer_use_cases import get_trainer
from src.shared.catalog_visibility import (
    CATALOG_STATE_DRAFT,
    CATALOG_STATE_HIDDEN,
    CATALOG_STATE_NEEDS_REVISION,
    CATALOG_STATE_PAUSED,
    CATALOG_STATE_PENDING_REVIEW,
    CATALOG_STATE_PUBLISHED,
    trainer_opted_into_catalog,
)

logger = logging.getLogger(__name__)

STEP_LABELS: tuple[str, ...] = (
    "Зашёл в бота",
    "Профиль: имя и город",
    "Услуги и место работы",
    "Расписание и слоты",
    "Скопировал ссылку клиентам",
    "Добавил клиента",
    "Первая запись",
)
STEP_COUNT = len(STEP_LABELS)

# Short admin wording for submission-tier gaps (the trainer-facing labels are sentences).
_MISSING_SHORT_RU: dict[str, str] = {
    "full_name": "имя",
    "phone": "телефон",
    "photo": "фото",
    "city": "город",
    "session_duration_minutes": "длительность занятия",
    "min_hours_before_booking": "окно записи",
    "services": "услуга",
    "arenas": "арена",
}

_CATALOG_LABEL_RU: dict[str, str] = {
    CATALOG_STATE_PUBLISHED: "В каталоге",
    CATALOG_STATE_PENDING_REVIEW: "На модерации",
    CATALOG_STATE_NEEDS_REVISION: "Нужны правки",
    CATALOG_STATE_PAUSED: "На паузе",
    CATALOG_STATE_HIDDEN: "Скрыт",
}

_STALL_AFTER: tuple[str, ...] = (
    "",
    "Не начал профиль",
    "Не добавил услуги и место",
    "Не собрал расписание",
    "Не скопировал ссылку клиентам",
    "Ссылка есть, клиентов нет",
    "Клиент есть, записей нет",
    "Работает",
)

_JOURNEY_SQL = text(
    """
    SELECT
        t.id,
        t.telegram_id,
        t.telegram_username,
        t.created_at AS joined_at,
        t.catalog_state,
        t.catalog_state_reason,
        NULLIF(TRIM(CONCAT_WS(' ', p.first_name, p.last_name)), '') AS display_name,
        (p.first_name IS NOT NULL AND TRIM(p.first_name) <> '' AND p.city_id IS NOT NULL) AS has_profile,
        (
            EXISTS (SELECT 1 FROM trainer_services ts WHERE ts.trainer_id = t.id)
            AND (
                t.primary_arena_id IS NOT NULL
                OR t.arena_work_format IS NOT NULL
                OR COALESCE(p.online_enabled, false)
                OR EXISTS (SELECT 1 FROM trainer_arenas ta WHERE ta.trainer_id = t.id)
            )
        ) AS has_services,
        (
            EXISTS (SELECT 1 FROM trainer_schedule_templates st WHERE st.trainer_id = t.id)
            OR EXISTS (SELECT 1 FROM slots s WHERE s.trainer_id = t.id)
        ) AS has_schedule,
        (SELECT COUNT(*) FROM slots s WHERE s.trainer_id = t.id AND s.status <> 'cancelled')::int AS slots_count,
        t.client_invite_link_first_copied_at AS link_copied_at,
        (SELECT COUNT(DISTINCT c.client_id) FROM (
            SELECT r.client_id FROM trainer_client_roster r WHERE r.trainer_id = t.id
            UNION
            SELECT b.client_id FROM bookings b WHERE b.trainer_id = t.id AND NOT b.is_sandbox
        ) c)::int AS clients_count,
        LEAST(
            (SELECT MIN(r.created_at) FROM trainer_client_roster r WHERE r.trainer_id = t.id),
            (SELECT MIN(b.created_at) FROM bookings b WHERE b.trainer_id = t.id AND NOT b.is_sandbox)
        ) AS first_client_at,
        (SELECT COUNT(*) FROM bookings b
          WHERE b.trainer_id = t.id AND NOT b.is_sandbox
            AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed'))::int AS bookings_count,
        (SELECT MIN(b.created_at) FROM bookings b
          WHERE b.trainer_id = t.id AND NOT b.is_sandbox
            AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')) AS first_booking_at,
        (SELECT MIN(f.first_used_at) FROM trainer_feature_first_use f
          WHERE f.trainer_id = t.id AND f.feature = 'weekly_template') AS schedule_at,
        GREATEST(
            t.created_at,
            t.client_invite_link_first_copied_at,
            p.onboarding_completed_at,
            (SELECT MAX(f.first_used_at) FROM trainer_feature_first_use f WHERE f.trainer_id = t.id),
            (SELECT MAX(b.created_at) FROM bookings b WHERE b.trainer_id = t.id),
            (SELECT MAX(r.created_at) FROM trainer_client_roster r WHERE r.trainer_id = t.id)
        ) AS last_activity_at,
        (
            SELECT ts.status || '|' || COALESCE(ts.expires_at::text, '')
            FROM trainer_subscriptions ts
            WHERE ts.trainer_id = t.id AND ts.started_at <= CURRENT_TIMESTAMP
            ORDER BY (ts.expires_at > CURRENT_TIMESTAMP) DESC, ts.expires_at DESC
            LIMIT 1
        ) AS sub_raw,
        ac.contacted_at
    FROM trainers t
    LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
    LEFT JOIN admin_trainer_contacts ac ON ac.trainer_id = t.id
    WHERE t.telegram_id IS NOT NULL
      AND t.status <> 'deactivated'
      AND NOT (t.telegram_id = ANY(:exclude_ids))
    ORDER BY t.created_at DESC, t.id DESC
    """
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _plan(sub_raw: str | None, now: datetime) -> dict[str, Any]:
    """Subscription summary: ``{"status": paid|trial|expired|none, "expires_at": iso|None}``."""
    if not sub_raw:
        return {"status": "none", "expires_at": None}
    status, _, expires = sub_raw.partition("|")
    expires_dt: datetime | None = None
    if expires:
        try:
            expires_dt = datetime.fromisoformat(expires)
        except ValueError:
            expires_dt = None
    if expires_dt is not None and expires_dt.tzinfo is None:
        expires_dt = expires_dt.replace(tzinfo=now.tzinfo)
    if expires_dt is not None and expires_dt <= now:
        return {"status": "expired", "expires_at": _iso(expires_dt)}
    kind = "trial" if status == "trial" else "paid" if status == "active" else "none"
    return {"status": kind, "expires_at": _iso(expires_dt)}


def build_catalog_info(state: str | None, reason: str | None, missing: list[str] | None) -> dict[str, Any]:
    """
    Is the trainer in the public catalog, and if not, what stops the card.

    ``missing`` holds submission-tier field keys (what blocks sending the card to a moderator);
    ``None`` means "not computed" and is reported as an empty list. Optional extras (bio,
    education) never appear: they do not block publication.
    """
    st = (state or "").strip() or CATALOG_STATE_DRAFT
    labels = [_MISSING_SHORT_RU[k] for k in (missing or []) if k in _MISSING_SHORT_RU]
    if st == CATALOG_STATE_DRAFT:
        wants = trainer_opted_into_catalog({"catalog_state": st, "catalog_state_reason": reason})
        label = "Не в каталоге" if not wants else "Хочет в каталог, не готов"
        if not labels and not wants:
            label = "Не в каталоге, карточка готова"
    else:
        label = _CATALOG_LABEL_RU.get(st, st)
    return {
        "state": st,
        "listed": st == CATALOG_STATE_PUBLISHED,
        "label": label,
        "missing": labels if st != CATALOG_STATE_PUBLISHED else [],
    }


def build_journey_row(row: Any, now: datetime, missing: list[str] | None = None) -> dict[str, Any]:
    """Pure transform of one SQL row into the API item (unit-tested without a database)."""
    done_flags = [
        True,
        bool(row.has_profile),
        bool(row.has_services),
        bool(row.has_schedule),
        row.link_copied_at is not None,
        bool(row.clients_count),
        bool(row.bookings_count),
    ]
    # The funnel is a path: a step counts only when every earlier one is done, so a trainer
    # who skipped ahead still shows where the first gap is.
    reached = 0
    for flag in done_flags:
        if not flag:
            break
        reached += 1
    dates = [
        _iso(row.joined_at),
        None,
        None,
        _iso(row.schedule_at),
        _iso(row.link_copied_at),
        _iso(row.first_client_at),
        _iso(row.first_booking_at),
    ]
    steps = [
        {
            "label": STEP_LABELS[i],
            "done": done_flags[i],
            "date": dates[i] if done_flags[i] else None,
        }
        for i in range(STEP_COUNT)
    ]
    return {
        "trainer_id": row.id,
        "telegram_id": row.telegram_id,
        "username": row.telegram_username or None,
        "name": row.display_name,
        "joined_at": _iso(row.joined_at),
        "last_activity_at": _iso(row.last_activity_at),
        "reached": reached,
        "working": reached == STEP_COUNT,
        "stall": _STALL_AFTER[reached],
        "steps": steps,
        "slots": row.slots_count,
        "clients": row.clients_count,
        "bookings": row.bookings_count,
        "plan": _plan(row.sub_raw, now),
        "contacted_at": _iso(row.contacted_at),
        "catalog": build_catalog_info(
            getattr(row, "catalog_state", None), getattr(row, "catalog_state_reason", None), missing
        ),
    }


async def _submission_gaps(session: AsyncSession, trainer_id: int) -> list[str] | None:
    """Submission-tier gaps for one trainer; None when the aggregate cannot be built."""
    try:
        trainer = await get_trainer(session, trainer_id)
        if trainer is None:
            return None
        return analyze_moderation_submission_readiness(trainer)[1]
    except Exception:  # noqa: BLE001 — one broken card must not blank the whole admin list
        logger.exception("journey: catalog gaps failed trainer_id=%s", trainer_id)
        return None


async def get_admin_trainer_journey(
    session: AsyncSession, *, exclude_telegram_ids: list[int] | None = None
) -> dict[str, Any]:
    """All trainers who opened the bot, newest first, with their path through the product."""
    result = await session.execute(_JOURNEY_SQL, {"exclude_ids": list(exclude_telegram_ids or [])})
    now = (await session.execute(text("SELECT CURRENT_TIMESTAMP"))).scalar_one()
    rows = result.all()
    items = []
    for r in rows:
        gaps = None
        if (r.catalog_state or "").strip() != CATALOG_STATE_PUBLISHED:
            gaps = await _submission_gaps(session, r.id)
        items.append(build_journey_row(r, now, gaps))
    return {
        "total": len(items),
        "step_labels": list(STEP_LABELS),
        "items": items,
    }


async def set_trainer_contacted(
    session: AsyncSession, *, trainer_id: int, contacted: bool, admin_telegram_id: int | None
) -> bool:
    """Mark/unmark «написали». Returns False when the trainer does not exist."""
    exists = (
        await session.execute(text("SELECT 1 FROM trainers WHERE id = :tid"), {"tid": trainer_id})
    ).first()
    if exists is None:
        return False
    if contacted:
        await session.execute(
            text(
                """
                INSERT INTO admin_trainer_contacts (trainer_id, admin_telegram_id)
                VALUES (:tid, :aid)
                ON CONFLICT (trainer_id) DO UPDATE
                SET contacted_at = now(), admin_telegram_id = EXCLUDED.admin_telegram_id
                """
            ),
            {"tid": trainer_id, "aid": admin_telegram_id},
        )
    else:
        await session.execute(
            text("DELETE FROM admin_trainer_contacts WHERE trainer_id = :tid"), {"tid": trainer_id}
        )
    await session.commit()
    return True
