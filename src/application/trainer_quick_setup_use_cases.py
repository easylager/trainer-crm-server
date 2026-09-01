"""
Onboarding v2, step one: turn two taps into a working week.

The whole first run is a single call. The trainer picks what they coach, how long a session runs, and taps the hours they usually
work; this module writes the services, the weekly template and two weeks of concrete slots,
and fills the product defaults nobody should be asked about on day one.

Session length IS asked — three chips, one tap. It is not a default: it decides how long every
generated slot is, and a wrong guess produces a schedule that looks fine and is silently wrong.

Deliberately **not** asked here — each has an event later that makes the question urgent and
obvious, which is when we ask it:

===================  ==================================================
field                asked at
===================  ==================================================
arena                first booking («где встречаетесь?»)
phone                first cancellation or reschedule
prices               first pass sale or price question
city / bio           only when the trainer wants a catalog card
photo                never asked — taken from the Telegram avatar on first /start
===================  ==================================================

A typical week is suggested rather than left blank: an empty grid is a form, a pre-filled grid
is a confirmation. The trainer changes what does not fit, which is a much cheaper action than
composing a schedule from nothing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.arena_schedule_preset import (
    GRID_HOURLY_MINUTE,
    fixed_slot_duration_minutes,
    get_arena_schedule_preset_raw,
    get_schedule_grid_preset_for_trainer,
)
from src.application.trainer_schedule_use_cases import (
    replace_templates_for_day,
    replace_week_with_template,
)

logger = logging.getLogger(__name__)

# Product defaults. Every one of these is editable later in «Настройки»; none is worth a first-run question.
DEFAULT_SESSION_DURATION_MINUTES = 60
DEFAULT_MIN_HOURS_BEFORE_BOOKING = 2
# Two weeks is the horizon a client actually plans in, and short enough that a wrong guess is cheap.
QUICK_SETUP_WEEKS = 2

# Suggested week for the ice vertical: early mornings before work/school, evenings after.
# Mon–Fri only — weekend ice is booked per-arena and varies too much to guess.
SUGGESTED_WEEKDAY_HOURS: tuple[int, ...] = (7, 8, 18, 19, 20)
SUGGESTED_WEEKDAYS: tuple[int, ...] = (0, 1, 2, 3, 4)


def suggested_week() -> list[dict[str, Any]]:
    """The pre-filled grid the trainer confirms or edits. Never an empty form."""
    return [
        {"day_of_week": d, "hours": list(SUGGESTED_WEEKDAY_HOURS)}
        for d in SUGGESTED_WEEKDAYS
    ]


async def trainer_has_weekly_template(session: AsyncSession, trainer_id: int) -> bool:
    """
    Has this trainer ever set up a week?

    This one boolean replaces the old five-status / three-tier machinery as the signal that
    separates «first run» from «came back». It is true exactly when the trainer has finished the
    only setup step the product asks for.
    """
    r = await session.execute(
        text("SELECT EXISTS(SELECT 1 FROM trainer_schedule_templates WHERE trainer_id = :tid)"),
        {"tid": trainer_id},
    )
    return bool(r.scalar())


async def seed_trainer_identity_from_telegram(
    session: AsyncSession,
    trainer_id: int,
    *,
    first_name: str | None,
    last_name: str | None,
) -> bool:
    """
    Take the trainer's name from Telegram instead of asking for it.

    Telegram already knows who this is, and the client will see this name on the booking screen.
    Fills only blanks — a trainer who typed their own name keeps it. Returns True when anything
    was written, so the caller can log a real change.
    """
    fn = (first_name or "").strip()[:120] or None
    ln = (last_name or "").strip()[:120] or None
    if not fn and not ln:
        return False
    r = await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, first_name, last_name)
            VALUES (:tid, :fn, :ln)
            ON CONFLICT (trainer_id) DO UPDATE SET
                first_name = COALESCE(NULLIF(TRIM(trainer_profiles.first_name), ''), EXCLUDED.first_name),
                last_name  = COALESCE(NULLIF(TRIM(trainer_profiles.last_name), ''), EXCLUDED.last_name)
            WHERE NULLIF(TRIM(trainer_profiles.first_name), '') IS NULL
               OR NULLIF(TRIM(trainer_profiles.last_name), '') IS NULL
            RETURNING trainer_id
            """
        ),
        {"tid": trainer_id, "fn": fn, "ln": ln},
    )
    wrote = r.fetchone() is not None
    await session.commit()
    return wrote


async def seed_trainer_photo_from_telegram(
    bot: Any,
    session: AsyncSession,
    trainer_id: int,
    telegram_user_id: int,
) -> bool:
    """
    Take the trainer's avatar from Telegram instead of asking them to upload one.

    Why it matters beyond saving a tap: the client opens the booking link expecting the person
    who sent it. A face they recognise is what makes the link feel like their coach and not like
    a form. A placeholder at that moment costs a booking, and the trainer never finds out.

    Skipped when the trainer already has a photo. Every failure path is silent by design — this
    runs inside ``/start`` and must never turn a missing avatar, an unconfigured bucket or a slow
    Telegram CDN into a broken first message. Returns True only when a photo was actually stored.
    """
    from src.application.trainer_use_cases import upload_trainer_photo_from_bytes

    try:
        r = await session.execute(
            text("SELECT EXISTS(SELECT 1 FROM trainer_photos WHERE trainer_id = :tid)"),
            {"tid": trainer_id},
        )
        if bool(r.scalar()):
            return False

        photos = await bot.get_user_profile_photos(user_id=telegram_user_id, limit=1)
        sizes = (getattr(photos, "photos", None) or [None])[0]
        if not sizes:
            return False
        # Sizes come smallest-first; the largest is the one worth storing.
        file_id = sizes[-1].file_id
        tg_file = await bot.get_file(file_id)
        buf = await bot.download_file(tg_file.file_path)
        body = buf.read() if hasattr(buf, "read") else bytes(buf)
        if not body:
            return False

        ok, _err, _key, _list = await upload_trainer_photo_from_bytes(
            session, trainer_id, body, "image/jpeg"
        )
        return bool(ok)
    except Exception:
        logger.info("telegram avatar seed skipped for trainer_id=%s", trainer_id, exc_info=True)
        return False


@dataclass(frozen=True)
class QuickSetupDay:
    day_of_week: int  # 0=Mon .. 6=Sun
    hours: tuple[int, ...]
    #: One venue per day — a trainer who splits a single day across two arenas is a real but
    #: rare case; onboarding covers "a different arena on a different day" (the common one)
    #: and leaves finer intra-day splits to schedule-editor later.
    arena_id: int | None = None


@dataclass(frozen=True)
class QuickSetupResult:
    slots_created: int
    #: Free slots a client could actually pick right now. This is the number we show the trainer —
    #: ``slots_created`` includes days already past in the current week and would overstate it.
    open_slots_ahead: int
    days_with_slots: int
    duration_minutes: int


class QuickSetupError(ValueError):
    """Input the trainer can fix; the message is shown as-is."""


def parse_quick_setup_days(raw: list[dict[str, Any]] | None) -> list[QuickSetupDay]:
    """
    Validate the grid payload. Raises QuickSetupError with a user-facing message.

    A day dict may repeat (e.g. the client sent a day row per arena tab it touched); the last
    occurrence for a given ``day_of_week`` wins, same as the arena-less path always did. That is
    what keeps "one arena per day" true by construction — see :class:`QuickSetupDay`.
    """
    days: dict[int, tuple[tuple[int, ...], int | None]] = {}
    for item in raw or []:
        try:
            dow = int(item.get("day_of_week"))
        except (TypeError, ValueError) as exc:
            raise QuickSetupError("Не понял день недели.") from exc
        if dow < 0 or dow > 6:
            raise QuickSetupError("День недели должен быть от 0 до 6.")
        raw_arena = item.get("arena_id")
        arena_id: int | None = None
        if raw_arena is not None:
            try:
                arena_id = int(raw_arena)
            except (TypeError, ValueError) as exc:
                raise QuickSetupError("Не понял площадку.") from exc
            if arena_id <= 0:
                raise QuickSetupError("Не понял площадку.")
        hours: set[int] = set()
        for h in item.get("hours") or []:
            try:
                hv = int(h)
            except (TypeError, ValueError) as exc:
                raise QuickSetupError("Не понял время начала.") from exc
            if hv < 0 or hv > 23:
                raise QuickSetupError("Время начала должно быть от 0 до 23.")
            hours.add(hv)
        if hours:
            days[dow] = (tuple(sorted(hours)), arena_id)
    if not days:
        raise QuickSetupError("Отметьте хотя бы одно время — иначе ученику нечего выбрать.")
    return [
        QuickSetupDay(day_of_week=d, hours=h, arena_id=aid)
        for d, (h, aid) in sorted(days.items())
    ]


async def _apply_profile_settings(session: AsyncSession, trainer_id: int, duration_minutes: int) -> None:
    """
    Write the session length the trainer picked; leave the booking window as a silent default.

    The two are deliberately handled differently:

    * ``session_duration_minutes`` is an **answer**, not a default — the trainer chose it on the
      first screen and every slot we just generated is that long. Writing anything else would
      leave the profile disagreeing with the schedule, and the trainer would find out only when
      a client books the wrong length. So this one overwrites.
    * ``min_hours_before_booking`` was never asked. It stays a default and is only filled when
      the profile row is created, so a trainer who tuned it keeps their value.

    Note the DB-level column defaults (45 / 3): the columns are effectively never NULL once a
    row exists, so COALESCE on the duration would silently keep 45 while generating 60-minute
    slots. That is exactly the bug this split avoids.
    """
    await session.execute(
        text(
            """
            INSERT INTO trainer_profiles (trainer_id, session_duration_minutes, min_hours_before_booking)
            VALUES (:tid, :dur, :win)
            ON CONFLICT (trainer_id) DO UPDATE SET
                session_duration_minutes = EXCLUDED.session_duration_minutes
            """
        ),
        {"tid": trainer_id, "dur": duration_minutes, "win": DEFAULT_MIN_HOURS_BEFORE_BOOKING},
    )


async def _set_services(session: AsyncSession, trainer_id: int, service_ids: list[int]) -> None:
    """
    Attach the sports the trainer picked, without prices.

    Prices are a separate decision with its own moment (first pass sale / first «сколько стоит?»),
    so trainer_services rows are created with NULL price_cents here.
    """
    if not service_ids:
        return
    r = await session.execute(
        text("SELECT id FROM services WHERE id = ANY(:ids)"),
        {"ids": list(service_ids)},
    )
    known = {int(row[0]) for row in r.fetchall()}
    unknown = [s for s in service_ids if s not in known]
    if unknown:
        raise QuickSetupError("Такой услуги нет в списке.")
    for sid in service_ids:
        await session.execute(
            text(
                """
                INSERT INTO trainer_services (trainer_id, service_id)
                VALUES (:tid, :sid)
                ON CONFLICT (trainer_id, service_id) DO NOTHING
                """
            ),
            {"tid": trainer_id, "sid": int(sid)},
        )


async def _validate_and_link_arenas(
    session: AsyncSession, trainer_id: int, arena_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """
    Check every referenced arena is real and active, link it to the trainer (idempotent), and
    return its grid preset keyed by id.

    Linking happens here rather than waiting for a separate profile step: a day the trainer just
    marked hours for needs its venue known *now*, for the client to see "куда идти" the moment
    they book — deferring it would recreate the exact gap this whole feature closes.
    """
    if not arena_ids:
        return {}
    r = await session.execute(
        text("SELECT id, name FROM arenas WHERE id = ANY(:ids) AND is_active = true"),
        {"ids": arena_ids},
    )
    found = {int(row[0]): row[1] for row in r.fetchall()}
    missing = [a for a in arena_ids if a not in found]
    if missing:
        raise QuickSetupError("Одна из выбранных площадок недоступна — обновите экран.")

    presets: dict[int, dict[str, Any]] = {}
    for aid in arena_ids:
        presets[aid] = await get_arena_schedule_preset_raw(session, aid)
        await session.execute(
            text(
                """
                INSERT INTO trainer_arenas (trainer_id, arena_id)
                VALUES (:tid, :aid)
                ON CONFLICT (trainer_id, arena_id) DO NOTHING
                """
            ),
            {"tid": trainer_id, "aid": aid},
        )

    # Only when the trainer works at exactly one venue does "the" primary arena mean anything.
    # Never overwrite a choice already made (site registration, profile, a previous run).
    if len(arena_ids) == 1:
        await session.execute(
            text(
                """
                UPDATE trainers SET primary_arena_id = :aid
                WHERE id = :tid AND primary_arena_id IS NULL
                """
            ),
            {"tid": trainer_id, "aid": arena_ids[0]},
        )
    return presets


def _day_grid(
    day: QuickSetupDay,
    presets: dict[int, dict[str, Any]],
    fallback_duration_minutes: int,
) -> tuple[dict[int, int], int]:
    """
    Resolve one day's (minute_to_capacity, duration_minutes) against its arena's real grid.

    No arena chosen → today's original behaviour: whole hours, trainer's own duration choice.
    Arena chosen → minutes shift by the arena's ``minute_offset`` (the ТЦ Замок case: slots at
    :15, not :00) and duration locks to the arena's ``slot_duration_minutes`` when it sets one,
    overriding what the trainer picked for that specific day — that lock is what stops a slot
    grid and a booking length from silently disagreeing.
    """
    offset = 0
    duration = fallback_duration_minutes
    if day.arena_id is not None:
        preset = presets[day.arena_id]
        if (preset.get("kind") or "").strip() == GRID_HOURLY_MINUTE:
            offset = int(preset.get("minute_offset") or 0)
        fixed = fixed_slot_duration_minutes(preset)
        if fixed is not None:
            duration = fixed
        h0 = int(preset.get("hour_start", 0))
        h1 = int(preset.get("hour_end", 23))
        out_of_range = [h for h in day.hours if h < h0 or h > h1]
        if out_of_range:
            raise QuickSetupError(
                f"Площадка работает с {h0}:00 до {h1}:00 — уберите время вне этого окна."
            )
    minute_to_capacity = {h * 60 + offset: 1 for h in day.hours}
    return minute_to_capacity, duration


async def run_trainer_quick_setup(
    session: AsyncSession,
    trainer_id: int,
    *,
    service_ids: list[int],
    days: list[QuickSetupDay],
    duration_minutes: int = DEFAULT_SESSION_DURATION_MINUTES,
    today: date | None = None,
) -> QuickSetupResult:
    """
    One call: services + defaults + weekly template + concrete slots for QUICK_SETUP_WEEKS.

    Idempotent by construction — templates are replaced per weekday and
    ``replace_week_with_template`` only clears *free* slots, so re-running never destroys a booking.
    """
    if duration_minutes < 15 or duration_minutes > 480:
        raise QuickSetupError("Длительность занятия должна быть от 15 до 480 минут.")

    await _set_services(session, trainer_id, service_ids)
    await _apply_profile_settings(session, trainer_id, duration_minutes)

    arena_ids_used = sorted({d.arena_id for d in days if d.arena_id is not None})
    presets = await _validate_and_link_arenas(session, trainer_id, arena_ids_used)

    # ``replace_templates_for_day`` validates its ``duration_minutes`` argument against the
    # trainer's *current* primary-arena preset even for an empty day (no minutes to actually
    # apply it to) — see trainer_schedule_use_cases.py. Linking a single-venue trainer above may
    # have just set ``primary_arena_id`` to an arena with a fixed duration; blindly passing the
    # trainer's global chip choice for every *other*, empty weekday would then fail validation
    # for a value nothing is even using. Resolve the one duration that is always safe to quote
    # for an empty day: the fixed duration of whatever arena is now primary, or the trainer's
    # own choice when nothing fixes it.
    trainer_preset = await get_schedule_grid_preset_for_trainer(session, trainer_id)
    empty_day_duration = fixed_slot_duration_minutes(trainer_preset) or duration_minutes

    by_day = {d.day_of_week: d for d in days}
    for dow in range(7):
        minute_to_capacity: dict[int, int] = {}
        minute_to_arena_id: dict[int, int] | None = None
        day_duration = empty_day_duration
        day = by_day.get(dow)
        if day is not None:
            minute_to_capacity, day_duration = _day_grid(day, presets, duration_minutes)
            if day.arena_id is not None:
                minute_to_arena_id = {m: day.arena_id for m in minute_to_capacity}
        # Days the trainer left empty are written too, so unchecking a day actually clears it.
        await replace_templates_for_day(
            session,
            trainer_id,
            dow,
            minute_to_capacity,
            day_duration,
            minute_to_arena_id=minute_to_arena_id,
        )

    base = today or date.today()
    week_start = base - timedelta(days=base.weekday())
    horizon = week_start + timedelta(weeks=QUICK_SETUP_WEEKS) - timedelta(days=1)
    created = 0
    for i in range(QUICK_SETUP_WEEKS):
        created += await replace_week_with_template(session, trainer_id, week_start + timedelta(weeks=i))
    await session.commit()

    r_open = await session.execute(
        text(
            """
            SELECT COUNT(*)::int FROM slots
            WHERE trainer_id = :tid
              AND status = 'available'
              AND slot_date >= :today
              AND slot_date <= :horizon
            """
        ),
        {"tid": trainer_id, "today": base, "horizon": horizon},
    )
    open_ahead = int(r_open.scalar() or 0)

    return QuickSetupResult(
        slots_created=created,
        open_slots_ahead=open_ahead,
        days_with_slots=len(by_day),
        duration_minutes=duration_minutes,
    )
