"""
Trainer onboarding checklist: submission readiness, full-profile flag, future slots, booking flags.
``profile_complete`` = moderation submission tier (8 criteria); ``full_profile_complete`` = dossier (12).
``tt_minimal_complete`` = 5-field TTV gate (schedule/bookings in Mini App before activation).
``has_upcoming_booking`` mirrors hub upcoming list logic (pending/confirmed on future-ended slots).
``has_any_booking`` = ever created a booking row for this trainer (includes ``cancelled`` /
``declined`` / sandbox). Deliberately unfiltered: a sandbox demo booking (the «Попробовать
на примере» onboarding path) must still flip this to True — activation parity with the real
flow, so trying the sandbox once actually feels like progress instead of the product still
saying «нет записей» right after (see ``tests/integration/test_sandbox_isolation.py``).
This is *not* the flag to gate «has a real client yet» decisions on — use
``has_real_booking`` for that (TASK-027): a real, non-sandbox booking not in
(``cancelled``/``declined``/``trainer_removed``), OR the one-time
``trainer_profiles.first_booking_milestone_at`` flag already claimed — so it does not
regress once a real booking was completed and later cancelled, while a sandbox demo or an
instantly-voided booking never counts as one in the first place. The old, single
``has_any_booking`` used to be read for both purposes at once — that conflation is exactly
what silently muted the share-link card and the reactivation series for trainers who had
only tried the sandbox demo or had a booking voided before it ever happened.
``has_completed_booking`` = at least one booking with status ``completed`` (hub nudge: client notes).
``last_completed_booking_client_id`` = ``client_id`` of the latest completed row by ``bookings.id`` (deep link).
``schedule_unlocked`` is True for every linked, non-deactivated trainer (onboarding v2:
moderation gates the catalog, not the trainer's own tools).
``arena_count`` / ``real_bookings_count`` / ``arena_work_format`` feed the single «next step» card.
``is_catalog_visible`` = trainer row flag (hub rhythm: catalog publication hint when false while active).
``catalog_invite_dismissed`` = trainer answered «Не сейчас» to the hub catalog invite (persisted, not per-device).
``catalog_missing_fields`` / ``catalog_missing_labels_ru`` = submission-tier gaps, so the catalog invite
names the same fields the profile will ask for instead of promising a shorter list.
``weekly_template_count`` = rows in ``trainer_schedule_templates`` (hub nudge after onboarding complete).
``slots_this_week_count`` = available/booked slots from today till end of current week.
``slots_next_week_count`` = available/booked slots for the next full week.
``available_slots_this_week_count`` / ``available_slots_next_week_count`` = free slots only (hub rhythm).
``bookings_this_week_count`` / ``bookings_next_week_count`` = non-cancelled bookings in that week window.
``open_loop_pending_bookings_count`` = future sessions with status ``pending`` (trainer confirm).
``open_loop_clients_no_upcoming_count`` = distinct clients in the same ``rel`` scope as CRM (bookings, roster, groups) with no future pending/confirmed session.
``open_loop_clients_no_telegram_count`` = clients in the same scope as ``list_trainer_clients``
(non-removed bookings, explicit roster, or active/trial group) with **no reachable bot chat** —
``sql_client_notify_telegram_id`` is null (own ``telegram_id`` or guardian account link). A child
profile linked to a parent Telegram must **not** inflate this count or the «Клиенты без бота» hub hint.
``fill_slots_invite_candidates_count`` = clients eligible for hub «напомнить о слотах»: CRM scope, Telegram linked,
no upcoming pending/confirmed session (same filter as ``list_trainer_fill_slots_invite_candidates``).
``has_crm_subscription_access`` = active trial/paid row with CRM base (``get_trainer_entitlements``); when false after
expiry, hub may show a soft tariff hint while the public catalog card can remain visible.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import count_trainer_fill_slots_invite_candidates
from src.application.client_profile_use_cases import sql_client_notify_telegram_id
from src.application.collective_use_cases import (
    STUDIO_ACCESS_MODE_ADMIN_ONLY,
    get_effective_studio_access_mode,
    get_trainer_studio_access_mode,
    list_active_collective_memberships,
)
from src.application.organization_capabilities import (
    capabilities_for_collective_membership,
    organization_capabilities_to_dict,
    resolve_solo_trainer_capabilities,
)
from src.application.subscription_tier_use_cases import trainer_has_crm_access
from src.application.trainer_client_invite_tracking import sql_trainer_has_real_booking
from src.application.trainer_use_cases import get_trainer, get_trainer_moderation_readiness
from src.infrastructure.db.models import (
    TRAINER_STATUS_ACTIVE,
    TRAINER_STATUS_DEACTIVATED,
    TRAINER_STATUS_PENDING_PROFILE,
)
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.trainer_status import normalize_trainer_status_value

# How far ahead to look for slots (matches product: "reasonable horizon").
_SLOT_HORIZON_DAYS = 56

_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"

# Inline: profile not ready for TTV path and no CRM trial yet.
_SLOTS_BOOKINGS_LOCKED_RU = "Аккаунт деактивирован — расписание и записи закрыты."
_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"


async def get_trainer_onboarding_checklist(session: AsyncSession, trainer_id: int) -> dict[str, Any] | None:
    """Aggregated checklist flags; None if trainer row missing."""
    trainer = await get_trainer(session, trainer_id)
    if not trainer:
        return None
    st = normalize_trainer_status_value(trainer.get("status"))
    is_active = st == TRAINER_STATUS_ACTIVE

    readiness = await get_trainer_moderation_readiness(session, trainer_id)
    profile_complete = bool(readiness and readiness.get("complete"))
    full_profile_complete = bool(readiness and readiness.get("full_profile_complete"))
    tt_minimal_complete = bool(readiness and readiness.get("tt_minimal_complete"))
    # «Отправлен на проверку», а не «готов к отправке»: profile_complete — это лишь 8 критериев.
    # Сбрасывается в False, когда модерация вернула фидбек, — шаг снова становится действием.
    moderation_submitted = bool(readiness and readiness.get("already_submitted_for_moderation"))

    out: dict[str, Any] = {
        "trainer_status": st,
        "is_active": is_active,
        "is_catalog_visible": bool(trainer.get("is_catalog_visible", False)),
        "profile_complete": profile_complete,
        "full_profile_complete": full_profile_complete,
        "tt_minimal_complete": tt_minimal_complete,
        "moderation_submitted": moderation_submitted,
        "weekly_template_count": 0,
        "slots_this_week_count": 0,
        "slots_next_week_count": 0,
        "available_slots_this_week_count": 0,
        "available_slots_next_week_count": 0,
        "bookings_this_week_count": 0,
        "bookings_next_week_count": 0,
        "has_future_available_slots": False,
        "has_future_slots": False,
        "has_any_booking": False,
        "has_real_booking": False,
        "has_upcoming_booking": False,
        "has_confirmed_booking": False,
        "has_completed_booking": False,
        "last_completed_booking_client_id": None,
        "slots_locked_reason": None,
        "bookings_locked_reason": None,
        "open_loop_pending_bookings_count": 0,
        "open_loop_clients_no_upcoming_count": 0,
        "open_loop_clients_no_telegram_count": 0,
        "fill_slots_invite_candidates_count": 0,
        "has_crm_subscription_access": False,
        "arena_count": 0,
        "real_bookings_count": 0,
        "arena_work_format": None,
        # «Не сейчас» на приглашении в каталог — ответ тренера, а не состояние вкладки.
        "catalog_invite_dismissed": False,
        # Что реально требуется для карточки (submission tier), чтобы приглашение в каталог
        # называло те же поля, которые потом попросит профиль.
        "catalog_missing_fields": list(readiness.get("missing_fields") or []) if readiness else [],
        "catalog_missing_labels_ru": list(readiness.get("missing_labels_ru") or []) if readiness else [],
    }

    r_dismiss = await session.execute(
        text("SELECT catalog_invite_dismissed_at FROM trainer_profiles WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    dismiss_row = r_dismiss.fetchone()
    out["catalog_invite_dismissed"] = bool(dismiss_row and dismiss_row[0] is not None)

    has_crm = await trainer_has_crm_access(session, trainer_id)
    out["has_crm_subscription_access"] = has_crm
    stored_studio_access_mode = await get_trainer_studio_access_mode(session, trainer_id)
    effective_studio_access_mode = await get_effective_studio_access_mode(session, trainer_id)
    out["studio_access_mode"] = stored_studio_access_mode

    if stored_studio_access_mode == STUDIO_ACCESS_MODE_ADMIN_ONLY:
        out["schedule_unlocked"] = True
        out["tt_minimal_complete"] = True
        out["profile_complete"] = True
        out["full_profile_complete"] = True
        # Center manager path: skip solo «первая запись» onboarding (hub step 2)
        # and «в каталог» (hub step 3) — карточку студийного тренера публикует не он сам.
        out["has_any_booking"] = True
        out["has_real_booking"] = True
        out["moderation_submitted"] = True
        out["slots_locked_reason"] = None
        out["bookings_locked_reason"] = None
        out["trainer_id"] = trainer_id
        memberships = await list_active_collective_memberships(session, trainer_id)
        if memberships:
            m = memberships[0]
            out["capabilities"] = capabilities_for_collective_membership(
                organization_format=m.organization_format,
                schedule_mode=m.schedule_mode,
                role=m.role,
                studio_access_mode=effective_studio_access_mode,
            )
        else:
            out["capabilities"] = organization_capabilities_to_dict(
                resolve_solo_trainer_capabilities(effective_studio_access_mode)
            )
        return out

    # Onboarding v2: nothing here locks the trainer out any more. Schedule and bookings are open
    # from the first second; ``is_active`` only says whether the public catalog lists them.
    # The old "locked until the anketa is complete" branch is gone deliberately — it was the
    # single biggest source of drop-off and of the tier machinery around it.
    if st == TRAINER_STATUS_DEACTIVATED:
        out["slots_locked_reason"] = _SLOTS_BOOKINGS_LOCKED_RU
        out["bookings_locked_reason"] = _SLOTS_BOOKINGS_LOCKED_RU
        out["schedule_unlocked"] = False
        out["trainer_id"] = trainer_id
        return out

    r_tpl = await session.execute(
        text("SELECT COUNT(*)::int FROM trainer_schedule_templates WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    tpl_row = r_tpl.fetchone()
    out["weekly_template_count"] = int(tpl_row[0]) if tpl_row and tpl_row[0] is not None else 0

    today = date.today()
    week_end = today + timedelta(days=(6 - today.weekday()))
    next_week_start = week_end + timedelta(days=1)
    next_week_end = next_week_start + timedelta(days=6)
    horizon = today + timedelta(days=_SLOT_HORIZON_DAYS)

    r_week = await session.execute(
        text(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE slot_date >= :d_this_from
                      AND slot_date <= :d_this_to
                      AND status IN ('available', 'booked')
                )::int AS this_week_cnt,
                COUNT(*) FILTER (
                    WHERE slot_date >= :d_next_from
                      AND slot_date <= :d_next_to
                      AND status IN ('available', 'booked')
                )::int AS next_week_cnt
            FROM slots
            WHERE trainer_id = :tid
            """
        ),
        {
            "tid": trainer_id,
            "d_this_from": today,
            "d_this_to": week_end,
            "d_next_from": next_week_start,
            "d_next_to": next_week_end,
        },
    )
    row_week = r_week.fetchone()
    if row_week:
        out["slots_this_week_count"] = int(row_week[0] or 0)
        out["slots_next_week_count"] = int(row_week[1] or 0)

    r_avail_book = await session.execute(
        text(
            """
            SELECT
                (
                    SELECT COUNT(*)::int FROM slots
                    WHERE trainer_id = :tid
                      AND slot_date >= :d_this_from
                      AND slot_date <= :d_this_to
                      AND status = 'available'
                ) AS avail_this,
                (
                    SELECT COUNT(*)::int FROM slots
                    WHERE trainer_id = :tid
                      AND slot_date >= :d_next_from
                      AND slot_date <= :d_next_to
                      AND status = 'available'
                ) AS avail_next,
                (
                    SELECT COUNT(*)::int
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.trainer_id = :tid
                      AND b.status NOT IN ('cancelled', 'declined')
                      AND NOT b.is_sandbox
                      AND s.slot_date >= :d_this_from
                      AND s.slot_date <= :d_this_to
                ) AS bookings_this,
                (
                    SELECT COUNT(*)::int
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.trainer_id = :tid
                      AND b.status NOT IN ('cancelled', 'declined')
                      AND NOT b.is_sandbox
                      AND s.slot_date >= :d_next_from
                      AND s.slot_date <= :d_next_to
                ) AS bookings_next
            """
        ),
        {
            "tid": trainer_id,
            "d_this_from": today,
            "d_this_to": week_end,
            "d_next_from": next_week_start,
            "d_next_to": next_week_end,
        },
    )
    row_ab = r_avail_book.fetchone()
    if row_ab:
        out["available_slots_this_week_count"] = int(row_ab[0] or 0)
        out["available_slots_next_week_count"] = int(row_ab[1] or 0)
        out["bookings_this_week_count"] = int(row_ab[2] or 0)
        out["bookings_next_week_count"] = int(row_ab[3] or 0)

    r = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM slots
                WHERE trainer_id = :tid
                  AND slot_date >= :d0
                  AND slot_date <= :d1
                  AND status = 'available'
            )
            """
        ),
        {"tid": trainer_id, "d0": today, "d1": horizon},
    )
    out["has_future_available_slots"] = bool(r.scalar())

    # Onboarding step «слоты»: any concrete slot in horizon (free or already booked — not only «available»).
    r_slots = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM slots
                WHERE trainer_id = :tid
                  AND slot_date >= :d0
                  AND slot_date <= :d1
                  AND status IN ('available', 'booked')
            )
            """
        ),
        {"tid": trainer_id, "d0": today, "d1": horizon},
    )
    out["has_future_slots"] = bool(r_slots.scalar())

    r2 = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_any_booking"] = bool(r2.scalar())

    r2b = await session.execute(
        text(f"SELECT {sql_trainer_has_real_booking(trainer_id_expr=':tid')}"),
        {"tid": trainer_id},
    )
    out["has_real_booking"] = bool(r2b.scalar())

    r_upcoming = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1
                FROM bookings b
                JOIN slots s ON s.id = b.slot_id
                WHERE b.trainer_id = :tid
                  AND b.status IN ('pending', 'confirmed')
                  AND s.status IN ('available', 'booked')
                  AND """
            + _SQL_SLOT_END_TS
            + """
                  > CURRENT_TIMESTAMP
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_upcoming_booking"] = bool(r_upcoming.scalar())

    r3 = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid
                  AND status IN ('confirmed', 'completed')
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_confirmed_booking"] = bool(r3.scalar())

    r_done = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM bookings
                WHERE trainer_id = :tid AND status = 'completed' AND NOT is_sandbox
            )
            """
        ),
        {"tid": trainer_id},
    )
    out["has_completed_booking"] = bool(r_done.scalar())
    r_last_done = await session.execute(
        text(
            """
            SELECT client_id FROM bookings
            WHERE trainer_id = :tid AND status = 'completed' AND NOT is_sandbox
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {"tid": trainer_id},
    )
    row_last = r_last_done.fetchone()
    out["last_completed_booking_client_id"] = (
        int(row_last[0]) if row_last and row_last[0] is not None else None
    )

    # Reached only by a linked, non-deactivated trainer — so the schedule is open, full stop.
    out["schedule_unlocked"] = True
    out["trainer_id"] = trainer_id

    # Facts the «next step» card needs and nothing else does.
    r_next = await session.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*)::int FROM trainer_arenas WHERE trainer_id = :tid) AS arena_cnt,
                (
                    SELECT COUNT(*)::int FROM bookings
                    WHERE trainer_id = :tid
                      AND status IN ('confirmed', 'completed')
                      AND NOT is_sandbox
                ) AS real_bookings_cnt
            """
        ),
        {"tid": trainer_id},
    )
    row_next = r_next.fetchone()
    out["arena_count"] = int(row_next[0] or 0) if row_next else 0
    out["real_bookings_count"] = int(row_next[1] or 0) if row_next else 0
    out["arena_work_format"] = (trainer.get("arena_work_format") or "").strip() or None

    # Open-loop rhythm hints: every CTE here MUST exclude sandbox identity (both ``b.is_sandbox`` and
    # ``c.is_sandbox``). Otherwise the demo client surfaces in «no upcoming session» / «invite to bot»
    # nudges — that's the leak we're closing.
    r_oloop = await session.execute(
        text(
            """
            SELECT
                (
                    SELECT COUNT(*)::int
                    FROM bookings b
                    JOIN slots s ON s.id = b.slot_id
                    WHERE b.trainer_id = :tid
                      AND b.status = 'pending'
                      AND NOT b.is_sandbox
                      AND s.status IN ('available', 'booked')
                      AND """
            + _SQL_SLOT_END_TS
            + """
                      > CURRENT_TIMESTAMP
                ) AS pending_cnt,
                (
                    WITH rel AS (
                        SELECT DISTINCT q.client_id
                        FROM (
                            SELECT b.client_id
                            FROM bookings b
                            JOIN clients c ON c.id = b.client_id
                            WHERE b.trainer_id = :tid
                              AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                              AND NOT b.is_sandbox
                              AND NOT c.is_sandbox
                            UNION
                            SELECT m.client_id
                            FROM training_group_members m
                            INNER JOIN training_groups g ON g.id = m.training_group_id
                            INNER JOIN clients c ON c.id = m.client_id
                            WHERE g.trainer_id = :tid
                              AND m.status IN ('active', 'trial')
                              AND NOT c.is_sandbox
                            UNION
                            SELECT r.client_id
                            FROM trainer_client_roster r
                            INNER JOIN clients c ON c.id = r.client_id
                            WHERE r.trainer_id = :tid
                              AND NOT c.is_sandbox
                        ) q
                    ),
                    has_upcoming AS (
                        SELECT DISTINCT b.client_id
                        FROM bookings b
                        JOIN slots s ON s.id = b.slot_id
                        WHERE b.trainer_id = :tid
                          AND b.status IN ('pending', 'confirmed')
                          AND NOT b.is_sandbox
                          AND s.status IN ('available', 'booked')
                          AND """
            + _SQL_SLOT_END_TS
            + """
                          > CURRENT_TIMESTAMP
                    )
                    SELECT COUNT(*)::int
                    FROM rel
                    WHERE NOT EXISTS (SELECT 1 FROM has_upcoming h WHERE h.client_id = rel.client_id)
                ) AS no_next_cnt,
                (
                    SELECT COUNT(DISTINCT c.id)::int
                    FROM clients c
                    WHERE """
            + sql_client_notify_telegram_id("c")
            + """ IS NULL
                      AND NOT c.is_sandbox
                      AND (
                          EXISTS (
                              SELECT 1 FROM bookings b
                              WHERE b.client_id = c.id
                                AND b.trainer_id = :tid
                                AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                                AND NOT b.is_sandbox
                          )
                          OR EXISTS (
                              SELECT 1 FROM trainer_client_roster r
                              WHERE r.client_id = c.id
                                AND r.trainer_id = :tid
                          )
                          OR EXISTS (
                              SELECT 1 FROM training_group_members m
                              INNER JOIN training_groups g ON g.id = m.training_group_id
                              WHERE m.client_id = c.id
                                AND g.trainer_id = :tid
                                AND m.status IN ('active', 'trial')
                          )
                      )
                ) AS no_tg_cnt
            """
        ),
        {"tid": trainer_id},
    )
    row_ol = r_oloop.fetchone()
    if row_ol:
        out["open_loop_pending_bookings_count"] = int(row_ol[0] or 0)
        out["open_loop_clients_no_upcoming_count"] = int(row_ol[1] or 0)
        out["open_loop_clients_no_telegram_count"] = int(row_ol[2] or 0)

    out["fill_slots_invite_candidates_count"] = await count_trainer_fill_slots_invite_candidates(
        session, trainer_id
    )

    memberships = await list_active_collective_memberships(session, trainer_id)
    if memberships:
        m = memberships[0]
        out["capabilities"] = capabilities_for_collective_membership(
            organization_format=m.organization_format,
            schedule_mode=m.schedule_mode,
            role=m.role,
            studio_access_mode=effective_studio_access_mode,
        )
    else:
        out["capabilities"] = organization_capabilities_to_dict(
            resolve_solo_trainer_capabilities(effective_studio_access_mode)
        )

    return out
