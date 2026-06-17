"""
Trainer hub unified action inbox — server-side source of truth for Wave B.

Aggregates pending confirmations, unanswered requests, and rhythm open-loop hints
from onboarding checklist + hub bookings preview. Dismiss state stays client-side
(localStorage); the API returns all rhythm candidates for the hub to filter.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.notification_hours import NOTIFICATION_TZ

_SQL_SLOT_END_TS = f"((s.slot_date + s.end_time) AT TIME ZONE '{NOTIFICATION_TZ}')"

HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD = 6


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return few
    return many


def _non_negative_int(v: Any) -> int:
    if v is None or v == "":
        return 0
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def _onboarding_booking_step_done(d: dict[str, Any]) -> bool:
    return bool(
        d.get("has_any_booking") or d.get("has_confirmed_booking") or d.get("has_upcoming_booking")
    )


def _onboarding_all_complete(d: dict[str, Any]) -> bool:
    if not _onboarding_booking_step_done(d):
        return False
    if d.get("is_active") and d.get("profile_complete"):
        return True
    if not d.get("is_active") and d.get("schedule_unlocked") and d.get("tt_minimal_complete"):
        return True
    return False


async def fetch_hub_pending_booking_ids(
    session: AsyncSession,
    trainer_id: int,
    *,
    limit: int = 50,
) -> list[int]:
    """Future pending bookings for hub confirm — same filter as open_loop_pending_bookings_count."""
    lim = max(1, min(int(limit), 200))
    r = await session.execute(
        text(
            """
            SELECT b.id
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
            ORDER BY s.slot_date, s.start_time, b.id
            LIMIT :lim
            """
        ),
        {"tid": int(trainer_id), "lim": lim},
    )
    return [int(row[0]) for row in r.fetchall()]


def _pending_booking_ids_from_hub_bookings(bookings: dict[str, Any] | None) -> list[int]:
    if not bookings:
        return []
    out: list[int] = []
    for day in bookings.get("days") or []:
        for b in day.get("bookings") or []:
            if str(b.get("status") or "").lower() != "pending":
                continue
            bid = b.get("id")
            if bid is None:
                continue
            out.append(int(bid))
    return out


def _inbox_item(
    *,
    item_id: str,
    kind: str,
    priority: int,
    title: str,
    primary_label: str,
    primary_action: str,
    subtitle: str = "",
    urgent: bool = False,
    count: int | None = None,
    dismissible: bool = False,
    secondary_label: str | None = None,
    secondary_action: str | None = None,
    booking_ids: list[int] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": item_id,
        "kind": kind,
        "priority": priority,
        "urgent": urgent,
        "title": title,
        "subtitle": subtitle,
        "primary_label": primary_label,
        "primary_action": primary_action,
        "dismissible": dismissible,
    }
    if count is not None:
        row["count"] = count
    if secondary_label and secondary_action:
        row["secondary_label"] = secondary_label
        row["secondary_action"] = secondary_action
    if booking_ids:
        row["booking_ids"] = booking_ids
    return row


def _build_hub_rhythm_inbox_candidates(onboarding: dict[str, Any]) -> list[dict[str, Any]]:
    """Rhythm hints from checklist — excludes open_loop_pending (merged into pending_bookings)."""
    out: list[dict[str, Any]] = []
    d = onboarding
    active = bool(d.get("is_active"))
    complete = _onboarding_all_complete(d)

    if _onboarding_booking_step_done(d):
        cat_vis = d.get("is_catalog_visible") is not False and d.get("is_catalog_visible") != 0
        in_public = active and bool(d.get("profile_complete")) and cat_vis
        if not in_public:
            body = ""
            if not active and not d.get("profile_complete"):
                body = (
                    "Чтобы вас находили в общем каталоге, доведите профиль до проверки: "
                    "так мы подтверждаем карточку перед публикацией."
                )
            elif not active and d.get("profile_complete"):
                body = (
                    "Профиль отправлен на проверку. После активации аккаунта вас смогут найти "
                    "в каталоге — это следующий шаг к новым клиентам из списка."
                )
            elif active and not d.get("profile_complete"):
                body = (
                    "Для показа в каталоге закройте критерии профиля — в разделе статуса видно, "
                    "что ещё важно для публикации."
                )
            elif active and not cat_vis:
                body = (
                    "Сейчас вас нет в общем списке. Включите «Показать в каталоге» в профиле, "
                    "когда будете готовы к новым обращениям оттуда."
                )
            if body:
                out.append(
                    _inbox_item(
                        item_id="catalog_publication",
                        kind="rhythm",
                        priority=108,
                        title=body,
                        primary_label="Профиль",
                        primary_action="profile_catalog",
                        dismissible=True,
                    )
                )

    if not active or not complete:
        return out

    out.append(
        _inbox_item(
            item_id="referral_growth",
            kind="rhythm",
            priority=66,
            title=(
                "До 60 бесплатных дней полного доступа — приглашайте коллег "
                "по реферальной программе. Подробности в разделе «Рефералы»."
            ),
            primary_label="Рефералы",
            primary_action="trainer_referral",
            dismissible=True,
        )
    )

    if d.get("has_crm_subscription_access") is False:
        return out

    avail_this = _non_negative_int(d.get("available_slots_this_week_count"))
    avail_next = _non_negative_int(d.get("available_slots_next_week_count"))
    book_this = _non_negative_int(d.get("bookings_this_week_count"))
    book_next = _non_negative_int(d.get("bookings_next_week_count"))
    slots_next = _non_negative_int(d.get("slots_next_week_count"))
    wd = _non_negative_int(d.get("weekly_template_count"))
    this_week_ready = _non_negative_int(d.get("slots_this_week_count")) > 0
    next_week_ready = _non_negative_int(d.get("slots_next_week_count")) > 0
    slot_deferred = wd == 0

    open_no_upcoming = _non_negative_int(d.get("open_loop_clients_no_upcoming_count"))
    open_no_tg = _non_negative_int(d.get("open_loop_clients_no_telegram_count"))
    fill_candidates = _non_negative_int(d.get("fill_slots_invite_candidates_count"))
    has_future_avail = bool(d.get("has_future_available_slots"))

    if open_no_upcoming > 0:
        no_next_base = (
            f"{open_no_upcoming} "
            f"{_plural_ru(open_no_upcoming, 'ученик', 'ученика', 'учеников')} "
            "пока без следующей записи"
        )
        if not has_future_avail:
            out.append(
                _inbox_item(
                    item_id="open_loop_no_next",
                    kind="rhythm",
                    priority=97,
                    urgent=True,
                    title=(
                        no_next_base
                        + ". В расписании сейчас нет свободных слотов — сначала добавьте окна, "
                        "чтобы можно было пригласить на конкретное время."
                    ),
                    primary_label="Расписание",
                    primary_action="schedule",
                    dismissible=True,
                )
            )
        elif fill_candidates > 0:
            remind_n = fill_candidates
            suffix = ""
            if open_no_tg > 0:
                suffix = (
                    f" · ещё {open_no_tg} "
                    f"{_plural_ru(open_no_tg, 'клиент', 'клиента', 'клиентов')} "
                    "не в боте — «Напомнить» им не уйдёт; пришлите общую ссылку с главной (кнопка «Связь»)"
                )
            item = _inbox_item(
                item_id="open_loop_no_next",
                kind="rhythm",
                priority=97,
                urgent=True,
                title=f"{remind_n} {_plural_ru(remind_n, 'ученик', 'ученика', 'учеников')} без следующей записи{suffix}.",
                primary_label="Напомнить",
                primary_action="fill_slots_invites",
                dismissible=True,
            )
            if open_no_tg > 0:
                item["secondary_label"] = "Клиенты без бота"
                item["secondary_action"] = "trainer_clients_invite_bot"
            out.append(item)
        else:
            out.append(
                _inbox_item(
                    item_id="open_loop_no_next",
                    kind="rhythm",
                    priority=97,
                    urgent=True,
                    title=(
                        no_next_base
                        + ". Напоминание в боте — только подключённым. Остальным: общая ссылка "
                        "с главной (кнопка «Связь»)."
                    ),
                    primary_label="Клиенты без бота",
                    primary_action="trainer_clients_invite_bot",
                    secondary_label="Рассылка в боте",
                    secondary_action="fill_slots_invites",
                    dismissible=True,
                )
            )

    if not slot_deferred and avail_next > 0 and fill_candidates > 0:
        out.append(
            _inbox_item(
                item_id="open_loop_free_next",
                kind="rhythm",
                priority=72,
                title=(
                    f"На следующей неделе {avail_next} "
                    f"{_plural_ru(avail_next, 'свободный слот', 'свободных слота', 'свободных слотов')} "
                    "— кому из клиентов в боте напомнить о записи?"
                ),
                primary_label="Напомнить",
                primary_action="fill_slots_invites",
                dismissible=True,
            )
        )

    if not slot_deferred and avail_this == 0 and book_this < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD:
        out.append(
            _inbox_item(
                item_id="slots_this_week",
                kind="rhythm",
                priority=100,
                urgent=True,
                title="На этой неделе нет свободных слотов. Добавьте окна, чтобы клиенты могли записаться.",
                primary_label="Добавить слоты",
                primary_action="schedule",
                dismissible=True,
            )
        )

    next_week_gap = slots_next == 0 or (avail_next == 0 and book_next < HUB_RHYTHM_BOOKINGS_LOW_THRESHOLD)
    if not slot_deferred and next_week_gap:
        out.append(
            _inbox_item(
                item_id="slots_next_week",
                kind="rhythm",
                priority=90,
                title="На следующей неделе пока нет слотов. Заполните расписание заранее.",
                primary_label="Добавить слоты",
                primary_action="schedule",
                dismissible=True,
            )
        )

    if wd == 0:
        tpl = (
            "Добавьте часы в шаблон расписания — потом неделю можно накатить из шаблона за пару шагов."
            if this_week_ready and next_week_ready
            else "Создайте шаблон недели с постоянными часами — так проще держать ритм и наполнять расписание."
        )
        out.append(
            _inbox_item(
                item_id="template",
                kind="rhythm",
                priority=104,
                title=tpl,
                primary_label="Шаблон в расписании",
                primary_action="template",
                dismissible=True,
            )
        )

    if d.get("has_completed_booking"):
        out.append(
            _inbox_item(
                item_id="client_notes",
                kind="rhythm",
                priority=40,
                title=(
                    "После завершённой записи можно кратко зафиксировать заметки в карточке клиента — "
                    "так проще вести следующие занятия."
                ),
                primary_label="Профиль клиента",
                primary_action="client_notes",
                dismissible=True,
            )
        )

    if (
        open_no_tg > 0
        and not any(x["id"] == "open_loop_no_next" for x in out)
    ):
        out.append(
            _inbox_item(
                item_id="open_loop_no_telegram",
                kind="rhythm",
                priority=88,
                title=(
                    f"{open_no_tg} {_plural_ru(open_no_tg, 'клиент', 'клиента', 'клиентов')} "
                    "ещё не в боте. Откройте список по кнопке и отправьте им пригласительную ссылку."
                ),
                primary_label="Клиенты без бота",
                primary_action="trainer_clients_invite_bot",
                dismissible=True,
            )
        )

    return out


def build_trainer_hub_inbox_badges(
    *,
    onboarding: dict[str, Any] | None,
    requests_count: int,
    pending_count: int,
    center_inbox_pending: int = 0,
    show_center_inbox: bool = False,
) -> dict[str, int]:
    """Tab bar badge counts — schedule / center / more / clients."""
    schedule = max(0, int(pending_count))
    more = max(0, int(requests_count))
    clients = 0
    center = max(0, int(center_inbox_pending)) if show_center_inbox else 0
    if onboarding:
        clients = _non_negative_int(onboarding.get("open_loop_clients_no_telegram_count"))
        if _onboarding_booking_step_done(onboarding):
            cat_vis = onboarding.get("is_catalog_visible") is not False and onboarding.get("is_catalog_visible") != 0
            in_public = (
                bool(onboarding.get("is_active"))
                and bool(onboarding.get("profile_complete"))
                and cat_vis
            )
            if not in_public:
                more += 1
    return {
        "schedule": schedule,
        "center": center,
        "more": more,
        "clients": clients if clients > 0 else 0,
    }


def build_hub_dual_summary(
    *,
    bookings: dict[str, Any] | None,
    center_inbox_pending: int,
    collective_slug: str,
    collective_label: str,
) -> dict[str, Any]:
    """Two-number glance for center_hybrid owners — personal today + center inbox."""
    today = (bookings or {}).get("today_sessions") or {}
    return {
        "personal_today_total": _non_negative_int(today.get("total")),
        "personal_today_remaining": _non_negative_int(today.get("remaining")),
        "center_inbox_pending": max(0, int(center_inbox_pending)),
        "collective_slug": collective_slug,
        "collective_label": collective_label,
    }


def build_trainer_hub_action_inbox(
    *,
    onboarding: dict[str, Any] | None,
    requests_count: int = 0,
    bookings: dict[str, Any] | None = None,
    schedule_unlocked: bool = False,
    pending_booking_ids: list[int] | None = None,
    center_inbox_pending: int = 0,
    show_center_inbox: bool = False,
) -> dict[str, Any]:
    """
    Build unified hub inbox payload for bootstrap and inbox-count endpoint.
    Operational items require schedule_unlocked (active or TTV booking-ready).
    """
    items: list[dict[str, Any]] = []
    pending_count = 0
    pending_ids: list[int] = []

    if onboarding:
        pending_count = _non_negative_int(onboarding.get("open_loop_pending_bookings_count"))
    if pending_booking_ids is not None:
        pending_ids = [int(x) for x in pending_booking_ids]
    else:
        pending_ids = _pending_booking_ids_from_hub_bookings(bookings)

    if schedule_unlocked and pending_count > 0:
        n = pending_count
        items.append(
            _inbox_item(
                item_id="pending_bookings",
                kind="pending",
                priority=100,
                urgent=True,
                count=n,
                title=(
                    f"{n} {_plural_ru(n, 'запись ждёт подтверждения', 'записи ждут подтверждения', 'записей ждут подтверждения')}"
                ),
                subtitle="До подтверждения клиент не увидит занятие как согласованное",
                primary_label="Подтвердить все" if n > 1 else "Подтвердить",
                primary_action="batch_confirm",
                dismissible=False,
                booking_ids=pending_ids,
            )
        )

    req_n = max(0, int(requests_count))
    if schedule_unlocked and req_n > 0:
        items.append(
            _inbox_item(
                item_id="unanswered_requests",
                kind="requests",
                priority=90,
                urgent=True,
                count=req_n,
                title=(
                    f"{req_n} {_plural_ru(req_n, 'новая заявка без ответа', 'новые заявки без ответа', 'новых заявок без ответа')}"
                ),
                subtitle="Ответьте клиентам в разделе «Заявки»",
                primary_label="Ответить",
                primary_action="trainer_requests",
                dismissible=False,
            )
        )

    center_n = max(0, int(center_inbox_pending))
    if show_center_inbox and center_n > 0:
        items.append(
            _inbox_item(
                item_id="center_session_bookings",
                kind="center_pending",
                priority=96,
                urgent=True,
                count=center_n,
                title=(
                    f"{center_n} "
                    f"{_plural_ru(center_n, 'заявка в центр', 'заявки в центр', 'заявок в центр')} "
                    "ждёт подтверждения"
                ),
                subtitle="Подтвердите или отклоните в расписании",
                primary_label="Открыть расписание",
                primary_action="schedule_editor",
                dismissible=False,
            )
        )

    if onboarding:
        items.extend(_build_hub_rhythm_inbox_candidates(onboarding))

    items.sort(key=lambda x: int(x.get("priority") or 0), reverse=True)
    badges = build_trainer_hub_inbox_badges(
        onboarding=onboarding,
        requests_count=req_n,
        pending_count=pending_count if schedule_unlocked else 0,
        center_inbox_pending=center_n,
        show_center_inbox=show_center_inbox,
    )
    return {
        "total_actionable": len(items),
        "badges": badges,
        "items": items,
    }
