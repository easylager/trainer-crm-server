"""
Render the digest dict (from ``src/application/trainer_digest_use_cases.py``) as a Telegram
HTML message. Tone rule: ``.cursor/rules/Product-voice.mdc`` — живой, не биллинг.

Design intent — habit-forming ritual, not a data dump:

  1) HERO            — emoji + warm hook + the number that matters most
  2) DETAIL          — scannable rows / bullets; inline tags surface risks (⚠) and wins (👋)
  3) ONE RECOMMENDATION (👉) — closes an open loop; always present so the message never ends flat

Entry points:
- ``format_morning_digest(digest)``            — today's run-sheet (requires ≥1 session).
- ``format_morning_digest_lite_owed_only``     — fallback for empty days with pending requests.
- ``format_weekly_digest(digest)``             — Sunday ledger + forward view + drought + rec.
"""
from __future__ import annotations

import html as html_lib
from datetime import date, time
from typing import Any

from src.bot import messages as msg


# =============================================================================
# Plural / text helpers (Russian)
# =============================================================================


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Russian plural: 1 → one, 2–4 → few, otherwise many. Handles teens."""
    mod10 = n % 10
    mod100 = n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return few
    return many


def _sessions_word(n: int) -> str:
    return _plural_ru(n, "тренировка", "тренировки", "тренировок")


def _requests_word(n: int) -> str:
    return _plural_ru(n, "заявка", "заявки", "заявок")


def _bookings_word(n: int) -> str:
    return _plural_ru(n, "запись", "записи", "записей")


_WEEKDAY_LABELS_RU = (
    "понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье",
)
_WEEKDAY_LABELS_RU_PREP = (
    "понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье",
)


def _weekday_label(d: Any) -> str:
    """Lowercase Russian weekday; ``d.weekday()`` is 0=Mon..6=Sun."""
    return _WEEKDAY_LABELS_RU[d.weekday()]


def _weekday_label_prep(d: Any) -> str:
    """Accusative ('в пятницу') for recommendations like 'В пятницу пусто'."""
    return _WEEKDAY_LABELS_RU_PREP[d.weekday()]


def _format_hhmm(t: time) -> str:
    return t.strftime("%H:%M")


def _format_duration_minutes(minutes: int) -> str:
    """Compact Russian duration: 90 → '1ч 30м', 120 → '2ч', 45 → '45м'."""
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return f"{h}ч {m}м"
    if h:
        return f"{h}ч"
    return f"{m}м"


def _format_money_cents(cents: int) -> str:
    """Belarusian Ruble. 6000 → '60 BYN', 6050 → '60,50 BYN'."""
    if cents <= 0:
        return "0 BYN"
    rubles, kop = divmod(int(cents), 100)
    if kop == 0:
        return f"{rubles} BYN"
    return f"{rubles},{kop:02d} BYN"


def _short_client_name(full_name: str) -> str:
    """'Ирина Ковалёва' → 'Ирина К.'. No-op for single-token names."""
    parts = (full_name or "").split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1][:1]}."
    return full_name or "Клиент"


def _h(text: str) -> str:
    """Escape user-derived strings before inserting into HTML-parsed Telegram message."""
    return html_lib.escape(text or "", quote=False)


def _format_catalog_pulse_line(pulse: dict[str, Any] | None, *, weekly: bool) -> str | None:
    """
    Optional positive catalog line for digests. Priority:
    (1) non-zero window favorites and/or Telegram clicks — only mention non-zero parts;
    (2) else lifetime profile views if > 0;
    (3) else None (leave digest unchanged in that dimension).
    """
    if not pulse:
        return None
    fav = int(pulse.get("favorites") or 0)
    clk = int(pulse.get("contact_clicks") or 0)
    pv = int(pulse.get("profile_views_total") or 0)

    head = "📈 "
    if weekly:
        intro = "<b>За прошлую неделю в каталоге</b> "
    else:
        intro = "<b>Вчера в каталоге</b> "

    if fav > 0 or clk > 0:
        chunks: list[str] = []
        if fav > 0:
            chunks.append(
                f"<b>{fav}</b> "
                f"{_plural_ru(fav, 'добавление в избранное', 'добавления в избранное', 'добавлений в избранное')}"
            )
        if clk > 0:
            chunks.append(
                f"<b>{clk}</b> "
                f"{_plural_ru(clk, 'переход в Telegram', 'перехода в Telegram', 'переходов в Telegram')}"
            )
        return head + intro + "— " + " и ".join(chunks) + "."

    if pv > 0:
        # Lifetime metric — no «вчера/неделя» framing (would contradict «всего»).
        return (
            "📈 Вашу карточку в каталоге уже смотрели "
            f"<b>{pv}</b> {_plural_ru(pv, 'раз', 'раза', 'раз')} всего."
        )
    return None


# =============================================================================
# Morning digest
# =============================================================================


def _digest_morning_hero_greeting(wall_time: time | None) -> str:
    """Приветствие по фактическому времени отправки (если тренер задал час вручную)."""
    if wall_time is None or wall_time.hour < 12:
        return msg.TRAINER_DIGEST_MORNING_GREETING
    if wall_time.hour < 17:
        return msg.TRAINER_DIGEST_MORNING_GREETING_DAY
    return msg.TRAINER_DIGEST_MORNING_GREETING_EVENING


def _digest_morning_lite_greet_phrase(wall_time: time | None) -> str:
    """Короткая вставка в lite-заголовок (с точкой перед «Сегодня»)."""
    if wall_time is None or wall_time.hour < 12:
        return "Доброе утро."
    if wall_time.hour < 17:
        return "Добрый день."
    return "Добрый вечер."


def format_morning_digest(
    digest: dict[str, Any], *, wall_time: time | None = None
) -> str:
    """
    Produces HTML-parsed Telegram text for today's run-sheet. ``digest`` must have at least
    one session (caller — the loop — is responsible for suppressing the push on empty days).
    Always ends with a single 👉 recommendation to close the open loop.
    """
    sessions = digest.get("sessions") or []
    if not sessions:
        raise ValueError(
            "format_morning_digest must not be called for empty days; "
            "loop should suppress the push instead."
        )

    lines: list[str] = [_format_morning_header(sessions, wall_time), ""]
    for s in sessions:
        lines.append(_format_session_row(s))

    gap_line = _format_longest_gap_line(digest.get("gaps") or [])
    owed_line = _format_owed_line(
        pending_requests_count=int(digest.get("pending_requests_count") or 0),
        pending_confirmations_count=int(digest.get("pending_confirmations_count") or 0),
    )
    if gap_line or owed_line:
        lines.append("")
        if gap_line:
            lines.append(gap_line)
        if owed_line:
            lines.append(owed_line)

    catalog_line = _format_catalog_pulse_line(digest.get("catalog_pulse"), weekly=False)
    if catalog_line:
        lines.append("")
        lines.append(catalog_line)

    rec = _pick_morning_recommendation(digest)
    lines.extend(["", rec])

    return "\n".join(lines).rstrip()


def _format_morning_header(
    sessions: list[dict[str, Any]], wall_time: time | None = None
) -> str:
    n = len(sessions)
    first_hhmm = _format_hhmm(sessions[0]["start_time"])
    greet = _digest_morning_hero_greeting(wall_time)
    if n == 1:
        return (
            f"{greet} "
            f"Сегодня одна {_sessions_word(1)} — в <b>{first_hhmm}</b>."
        )
    return (
        f"{greet} "
        f"Сегодня <b>{n}</b> {_sessions_word(n)}, первая в <b>{first_hhmm}</b>."
    )


def _format_session_row(sess: dict[str, Any]) -> str:
    """``HH:MM · Имя Ф. · Площадка · 👋 первая тренировка · ⚠ ждёт подтверждения``."""
    hhmm = _format_hhmm(sess["start_time"])
    name = _h(_short_client_name(sess.get("client_name") or "Клиент"))
    parts = [f"<b>{hhmm}</b>", name]
    arena = sess.get("arena_name")
    if arena:
        parts.append(_h(arena))
    if sess.get("is_first_time"):
        parts.append(msg.TRAINER_DIGEST_SESSION_TAG_FIRST_TIMER)
    if sess.get("status") == "pending":
        parts.append(msg.TRAINER_DIGEST_SESSION_TAG_PENDING)
    return " · ".join(parts)


def _format_longest_gap_line(gaps: list[dict[str, Any]]) -> str | None:
    """Pick the longest gap (most informative). Returns None when no gaps above threshold."""
    if not gaps:
        return None
    longest = max(gaps, key=lambda g: g["duration_minutes"])
    return msg.TRAINER_DIGEST_GAP_LINE.format(
        from_time=_format_hhmm(longest["from_time"]),
        to_time=_format_hhmm(longest["to_time"]),
        duration=_format_duration_minutes(int(longest["duration_minutes"])),
    )


def _format_owed_line(
    *, pending_requests_count: int, pending_confirmations_count: int
) -> str | None:
    """Single '💬 Ждут ответа' line if there's anything waiting; otherwise silent."""
    r, c = pending_requests_count, pending_confirmations_count
    if r == 0 and c == 0:
        return None
    if r > 0 and c == 0:
        return msg.TRAINER_DIGEST_OWED_LINE_REQUESTS_ONLY.format(
            count=r, word=_requests_word(r)
        )
    if r == 0 and c > 0:
        return msg.TRAINER_DIGEST_OWED_LINE_CONFIRMS_ONLY.format(
            count=c, word=_bookings_word(c)
        )
    return msg.TRAINER_DIGEST_OWED_LINE_BOTH.format(
        req_count=r,
        req_word=_requests_word(r),
        conf_count=c,
        conf_word=_bookings_word(c),
    )


def _pick_morning_recommendation(digest: dict[str, Any]) -> str:
    """
    Priority ladder for the single closing 👉 line. Order is chosen for retention leverage:
    first-timer > pending trainer confirmation > open catalog requests > big gap > neutral.
    """
    sessions = digest.get("sessions") or []

    first_timer = next((s for s in sessions if s.get("is_first_time")), None)
    if first_timer:
        return msg.TRAINER_DIGEST_MORNING_REC_FIRST_TIMER.format(
            name=_h(_short_client_name(first_timer.get("client_name") or "Клиент")),
        )

    pending_sess = next((s for s in sessions if s.get("status") == "pending"), None)
    if pending_sess:
        return msg.TRAINER_DIGEST_MORNING_REC_PENDING_CONFIRM.format(
            name=_h(_short_client_name(pending_sess.get("client_name") or "Клиент")),
            time=_format_hhmm(pending_sess["start_time"]),
        )

    req_count = int(digest.get("pending_requests_count") or 0)
    if req_count > 0:
        return msg.TRAINER_DIGEST_MORNING_REC_PENDING_REQUESTS.format(
            count=req_count, word=_requests_word(req_count),
        )

    if digest.get("gaps"):
        return msg.TRAINER_DIGEST_MORNING_REC_BIG_GAP

    return msg.TRAINER_DIGEST_MORNING_REC_ALL_CLEAR


def format_morning_digest_lite_owed_only(
    digest: dict[str, Any], *, wall_time: time | None = None
) -> str | None:
    """
    Lite morning text used when trainer has 0 sessions today but ≥1 open catalog request.
    Replaces the old ``run_daily_request_reminder_loop``: surfaces pending work without
    inventing operational content for an empty day. Returns ``None`` when there is
    nothing to say (caller must skip the send).
    """
    count = int(digest.get("pending_requests_count") or 0)
    if count <= 0:
        return None
    header = msg.TRAINER_DIGEST_MORNING_LITE_HEADER.format(
        greet=_digest_morning_lite_greet_phrase(wall_time),
        count=count,
        word=_requests_word(count),
    )
    catalog_line = _format_catalog_pulse_line(digest.get("catalog_pulse"), weekly=False)
    parts = [header]
    if catalog_line:
        parts.extend(["", catalog_line])
    parts.extend(["", msg.TRAINER_DIGEST_MORNING_LITE_REC])
    return "\n".join(parts)


# =============================================================================
# Sunday weekly digest
# =============================================================================


def format_weekly_digest(digest: dict[str, Any]) -> str:
    """
    Structure: hero → 📊 past ledger → 📅 upcoming view → optional drought → 👉 recommendation.
    Always ends with one recommendation so the message doesn't trail off flat.
    """
    lines: list[str] = [msg.TRAINER_DIGEST_WEEKLY_GREETING, ""]

    catalog_line = _format_catalog_pulse_line(digest.get("catalog_pulse"), weekly=True)
    if catalog_line:
        lines.append(catalog_line)
        lines.append("")

    lines.extend(_format_past_section(digest.get("past_week") or {}))
    lines.append("")
    lines.extend(_format_upcoming_section(digest.get("upcoming_week") or {}))

    drought_line = _format_drought_line(digest.get("drought") or {})
    if drought_line:
        lines.extend(["", drought_line])

    lines.extend(["", _pick_weekly_recommendation(digest)])

    return "\n".join(lines).rstrip()


def _format_past_section(past: dict[str, Any]) -> list[str]:
    """📊 header + bullets. Empty week gets a single neutral 'бывает'-line."""
    completed = int(past.get("completed_count") or 0)
    cash = int(past.get("cash_cents") or 0)
    pass_cnt = int(past.get("pass_sessions_count") or 0)
    cert = int(past.get("cert_cents") or 0)

    out: list[str] = [msg.TRAINER_DIGEST_WEEKLY_PAST_HEADER]
    if completed == 0:
        out.append(msg.TRAINER_DIGEST_WEEKLY_PAST_EMPTY)
        return out

    out.append(msg.TRAINER_DIGEST_WEEKLY_PAST_COMPLETED.format(
        count=completed, word=_sessions_word(completed),
    ))
    if cash > 0:
        out.append(msg.TRAINER_DIGEST_WEEKLY_PAST_CASH.format(cash=_format_money_cents(cash)))
    if pass_cnt > 0:
        out.append(msg.TRAINER_DIGEST_WEEKLY_PAST_PASSES.format(
            count=pass_cnt, word=_sessions_word(pass_cnt),
        ))
    if cert > 0:
        out.append(msg.TRAINER_DIGEST_WEEKLY_PAST_CERTS.format(cash=_format_money_cents(cert)))
    return out


def _format_upcoming_section(upcoming: dict[str, Any]) -> list[str]:
    """📅 header + bullets. Empty week gets a single 'пока пустая'-line."""
    count = int(upcoming.get("sessions_count") or 0)
    out: list[str] = [msg.TRAINER_DIGEST_WEEKLY_UPCOMING_HEADER]
    if count == 0:
        out.append(msg.TRAINER_DIGEST_WEEKLY_UPCOMING_EMPTY)
        return out

    out.append(msg.TRAINER_DIGEST_WEEKLY_UPCOMING_COUNT.format(
        count=count, word=_sessions_word(count),
    ))

    new_clients = upcoming.get("new_clients") or []
    if new_clients:
        names = ", ".join(
            _h(_short_client_name(c.get("client_name") or "Клиент"))
            for c in new_clients
        )
        out.append(msg.TRAINER_DIGEST_WEEKLY_NEW_CLIENTS.format(names=names))

    empty_days = upcoming.get("empty_days") or []
    if empty_days and len(empty_days) < 7:
        labels = ", ".join(_weekday_label(d) for d in empty_days)
        out.append(msg.TRAINER_DIGEST_WEEKLY_EMPTY_DAYS.format(days=labels))

    heaviest = upcoming.get("heaviest_day")
    if heaviest and int(heaviest.get("count") or 0) >= 3:
        out.append(msg.TRAINER_DIGEST_WEEKLY_HEAVIEST_DAY.format(
            label=_weekday_label(heaviest["date"]),
            count=int(heaviest["count"]),
            word=_sessions_word(int(heaviest["count"])),
        ))
    return out


def _pick_weekly_recommendation(digest: dict[str, Any]) -> str:
    """
    Priority: drought (already rendered above, so skip here) → empty day on a non-empty
    week → very heavy day → new clients this week → very quiet upcoming → all-good close.
    """
    upcoming = digest.get("upcoming_week") or {}
    upcoming_count = int(upcoming.get("sessions_count") or 0)
    empty_days = upcoming.get("empty_days") or []
    heaviest = upcoming.get("heaviest_day") or {}
    new_clients = upcoming.get("new_clients") or []

    if upcoming_count > 0 and empty_days and len(empty_days) < 7:
        first_empty = empty_days[0]
        return msg.TRAINER_DIGEST_WEEKLY_REC_EMPTY_DAY.format(
            day=_weekday_label_prep(first_empty),
        )

    if heaviest and int(heaviest.get("count") or 0) >= 4:
        return msg.TRAINER_DIGEST_WEEKLY_REC_HEAVY_DAY.format(
            day=_weekday_label(heaviest["date"]).capitalize(),
        )

    if new_clients:
        names = ", ".join(
            _h(_short_client_name(c.get("client_name") or "Клиент"))
            for c in new_clients
        )
        return msg.TRAINER_DIGEST_WEEKLY_REC_NEW_CLIENTS.format(names=names)

    if upcoming_count == 0:
        return msg.TRAINER_DIGEST_WEEKLY_REC_QUIET

    return msg.TRAINER_DIGEST_WEEKLY_REC_ALL_GOOD


def _format_drought_line(drought: dict[str, Any]) -> str | None:
    """Drought ladder rendered as one soft-nudge line. ``case=7`` → None (silent)."""
    if not drought.get("triggered"):
        return None
    case = drought.get("case")
    data = drought.get("data") or {}

    if case == 1:
        count = int(data.get("open_requests_count") or 0)
        return msg.TRAINER_DIGEST_DROUGHT_OPEN_REQUESTS.format(
            count=count, word=_requests_word(count)
        )
    if case == 2:
        return msg.TRAINER_DIGEST_DROUGHT_CATALOG_HIDDEN
    if case == 3:
        return msg.TRAINER_DIGEST_DROUGHT_NO_SLOTS.format(
            horizon_days=int(data.get("horizon_days") or 0)
        )
    if case == 4:
        clients = data.get("clients") or []
        names = ", ".join(
            _h(_short_client_name(c.get("client_name") or "Клиент")) for c in clients
        )
        return msg.TRAINER_DIGEST_DROUGHT_DORMANT.format(names=names)
    if case == 5:
        return msg.TRAINER_DIGEST_DROUGHT_PROFILE_INCOMPLETE
    if case == 6:
        return msg.TRAINER_DIGEST_DROUGHT_NO_TEMPLATE
    return None


__all__ = [
    "format_morning_digest",
    "format_morning_digest_lite_owed_only",
    "format_weekly_digest",
]
