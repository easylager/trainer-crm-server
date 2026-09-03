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
class QuickSetupSlot:
    """
    One start the trainer marked, at the precision the template actually stores.

    ``start_minute`` is minutes from midnight, so 13:25 survives the round-trip. ``None`` for
    ``duration_minutes`` means «resolve it» — the arena's fixed duration if it sets one, else
    the trainer's own choice.
    """

    start_minute: int
    duration_minutes: int | None = None
    arena_id: int | None = None


@dataclass(frozen=True)
class QuickSetupDay:
    day_of_week: int  # 0=Mon .. 6=Sun
    #: Hour-grid shorthand: whole hours, one venue for all of them. Kept because most of the
    #: screen still works this way; normalized into ``slots`` before anything is written.
    hours: tuple[int, ...] = ()
    arena_id: int | None = None
    #: Explicit starts, carried through unchanged. This is what brings back a slot at 13:25, or
    #: a second venue inside the same day — neither of which the hour grid can express.
    slots: tuple[QuickSetupSlot, ...] = ()

    def resolved_slots(self, arena_offset: int = 0) -> tuple[QuickSetupSlot, ...]:
        """
        The day as it will be written: hours shifted onto the venue's grid, plus explicit starts.

        Both shapes arrive together for the same day and that is normal, not a client bug — the
        screen draws part of a day on its hour grid and carries the rest verbatim. On a collision
        the explicit slot wins: it came out of the template with a duration and a venue already
        decided, and the hour is only a coarser way of naming the same start.
        """
        merged: dict[int, QuickSetupSlot] = {
            h * 60 + arena_offset: QuickSetupSlot(
                start_minute=h * 60 + arena_offset, arena_id=self.arena_id
            )
            for h in self.hours
        }
        for slot in self.slots:
            merged[slot.start_minute] = slot
        return tuple(merged[m] for m in sorted(merged))


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

    Two shapes are accepted on the same field:

    * ``{"day_of_week": 0, "hours": [7, 18], "arena_id": 5}`` — the hour grid, one venue for
      the day. Still what the screen sends for everything it can draw.
    * ``{"day_of_week": 0, "slots": [{"start_minute": 805, "duration_minutes": 60,
      "arena_id": 5}, ...]}`` — explicit starts. This is how a slot at 13:25, or a day split
      between two venues, comes back unchanged after the trainer re-opens the screen.

    Both shapes may describe the same day, and routinely do: the screen sends the part it drew on
    its hour grid as ``hours`` and the part it could not draw as ``slots``. Repeated
    ``day_of_week`` entries are **merged**, keyed by start minute, rather than the last one
    winning — a day is a set of starts, and dropping the earlier entry is how the previous
    contract quietly deleted a venue.
    """
    by_day: dict[int, dict[int, QuickSetupSlot]] = {}
    hour_shorthand: dict[int, tuple[set[int], int | None]] = {}

    def _arena(raw_value: Any) -> int | None:
        if raw_value is None:
            return None
        try:
            aid = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise QuickSetupError("Не понял площадку.") from exc
        if aid <= 0:
            raise QuickSetupError("Не понял площадку.")
        return aid

    for item in raw or []:
        try:
            dow = int(item.get("day_of_week"))
        except (TypeError, ValueError) as exc:
            raise QuickSetupError("Не понял день недели.") from exc
        if dow < 0 or dow > 6:
            raise QuickSetupError("День недели должен быть от 0 до 6.")
        day_arena = _arena(item.get("arena_id"))

        for raw_slot in item.get("slots") or []:
            try:
                minute = int(raw_slot.get("start_minute"))
            except (TypeError, ValueError, AttributeError) as exc:
                raise QuickSetupError("Не понял время начала.") from exc
            if minute < 0 or minute > 24 * 60 - 1:
                raise QuickSetupError("Время начала должно быть внутри суток.")
            raw_dur = raw_slot.get("duration_minutes")
            duration: int | None = None
            if raw_dur is not None:
                try:
                    duration = int(raw_dur)
                except (TypeError, ValueError) as exc:
                    raise QuickSetupError("Не понял длительность.") from exc
                if duration < 15 or duration > 480:
                    raise QuickSetupError("Длительность занятия должна быть от 15 до 480 минут.")
            slot_arena = _arena(raw_slot.get("arena_id"))
            by_day.setdefault(dow, {})[minute] = QuickSetupSlot(
                start_minute=minute,
                duration_minutes=duration,
                arena_id=slot_arena if slot_arena is not None else day_arena,
            )

        raw_hours = item.get("hours") or []
        if raw_hours:
            hours, _prev_arena = hour_shorthand.get(dow, (set(), None))
            for h in raw_hours:
                try:
                    hv = int(h)
                except (TypeError, ValueError) as exc:
                    raise QuickSetupError("Не понял время начала.") from exc
                if hv < 0 or hv > 23:
                    raise QuickSetupError("Время начала должно быть от 0 до 23.")
                hours.add(hv)
            hour_shorthand[dow] = (hours, day_arena)

    out: list[QuickSetupDay] = []
    for dow in sorted(set(by_day) | set(hour_shorthand)):
        slots = tuple(by_day.get(dow, {})[m] for m in sorted(by_day.get(dow, {})))
        hours, hour_arena = hour_shorthand.get(dow, (set(), None))
        if not slots and not hours:
            continue
        out.append(
            QuickSetupDay(
                day_of_week=dow,
                hours=tuple(sorted(hours)),
                arena_id=hour_arena,
                slots=slots,
            )
        )
    if not out:
        raise QuickSetupError("Отметьте хотя бы одно время — иначе ученику нечего выбрать.")
    return out


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
) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    """
    Resolve one day into (minute→capacity, minute→arena_id, minute→duration).

    The hour shorthand shifts onto the venue's grid (the ТЦ Замок case: slots at :15, not :00)
    and takes the arena's fixed duration when it sets one, overriding the trainer's own chip for
    that day — that lock is what stops a slot grid and a booking length from silently disagreeing.

    Explicit ``slots`` are honoured as given: they came out of the template unchanged and putting
    them back through the hour grid is exactly how minutes and second venues got lost before.
    Their duration is still resolved per venue when the payload did not carry one.
    """
    offset = 0
    if day.arena_id is not None:
        preset = presets[day.arena_id]
        if (preset.get("kind") or "").strip() == GRID_HOURLY_MINUTE:
            offset = int(preset.get("minute_offset") or 0)

    minute_to_capacity: dict[int, int] = {}
    minute_to_arena_id: dict[int, int] = {}
    minute_to_duration: dict[int, int] = {}
    for slot in day.resolved_slots(offset):
        minute = int(slot.start_minute)
        duration = slot.duration_minutes
        if slot.arena_id is not None:
            preset = presets[slot.arena_id]
            fixed = fixed_slot_duration_minutes(preset)
            if fixed is not None:
                duration = fixed
            h0 = int(preset.get("hour_start", 0))
            h1 = int(preset.get("hour_end", 23))
            if not (h0 <= minute // 60 <= h1):
                raise QuickSetupError(
                    f"Площадка работает с {h0}:00 до {h1}:00 — уберите время вне этого окна."
                )
            minute_to_arena_id[minute] = slot.arena_id
        minute_to_capacity[minute] = 1
        minute_to_duration[minute] = int(duration or fallback_duration_minutes)
    return minute_to_capacity, minute_to_arena_id, minute_to_duration


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

    arena_ids_used = sorted(
        {
            aid
            for d in days
            for aid in ([d.arena_id] + [sl.arena_id for sl in d.slots])
            if aid is not None
        }
    )
    presets = await _validate_and_link_arenas(session, trainer_id, arena_ids_used)

    by_day = {d.day_of_week: d for d in days}
    for dow in range(7):
        minute_to_capacity: dict[int, int] = {}
        minute_to_arena_id: dict[int, int] = {}
        minute_to_duration: dict[int, int] = {}
        day = by_day.get(dow)
        if day is not None:
            minute_to_capacity, minute_to_arena_id, minute_to_duration = _day_grid(
                day, presets, duration_minutes
            )
        # Days the trainer left empty are written too, so unchecking a day actually clears it —
        # but only its individual rows: onboarding cannot draw group classes, so it must not
        # delete them either.
        await replace_templates_for_day(
            session,
            trainer_id,
            dow,
            minute_to_capacity,
            duration_minutes,
            minute_to_arena_id=minute_to_arena_id or None,
            minute_to_duration=minute_to_duration or None,
            only_capacity_one=True,
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
