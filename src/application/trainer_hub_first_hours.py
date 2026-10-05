"""
Первые часы прямо с главной — ответ на единственный вопрос дня ноль (TASK-173).

Тренер прошёл онбординг, но не отметил ни одного часа. Пока слотов нет, его ссылка
на запись приводит ученика на «Нет свободных слотов на эту неделю», поэтому хаб не
просит её отправить, а спрашивает про время и принимает ответ на месте.

Пресет разворачивается тем же путём, что и онбординг (``run_trainer_quick_setup``):
недельный шаблон плюс две недели конкретных слотов, с теми же проверками часов работы
площадки и её сетки. Услуги и город сюда намеренно не передаются: пустой ``service_ids``
не трогает привязанные услуги, ``city_id=None`` сохраняет текущий город. Этот вызов
добавляет расписание и больше ничего — он не часть онбординга и не повторяет его.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.trainer_quick_setup_use_cases import (
    DEFAULT_SESSION_DURATION_MINUTES,
    QUICK_SETUP_WEEKS,
    QuickSetupDay,
    QuickSetupError,
    run_trainer_quick_setup,
)


@dataclass(frozen=True)
class FirstHoursPreset:
    key: str
    #: 0=Mon .. 6=Sun
    days: tuple[int, ...]
    #: Whole hours on the trainer's local grid; the arena's own grid shifts them if it has one.
    hours: tuple[int, ...]
    label_ru: str
    hint_ru: str


#: Два ответа покрывают почти всех: вечерние будни и утро выходных. Третий ответ —
#: «своё время» — не пресет, он уводит в расписание и сюда не приходит.
FIRST_HOURS_PRESETS: dict[str, FirstHoursPreset] = {
    "weekday_evening": FirstHoursPreset(
        key="weekday_evening",
        days=(0, 2, 4),
        hours=(18, 19, 20),
        label_ru="Будни по вечерам",
        hint_ru="пн, ср, пт · 18:00–21:00",
    ),
    "weekend_morning": FirstHoursPreset(
        key="weekend_morning",
        days=(5, 6),
        hours=(10, 11, 12, 13),
        label_ru="Выходные с утра",
        hint_ru="сб, вс · 10:00–14:00",
    ),
}


@dataclass(frozen=True)
class FirstHoursResult:
    open_slots_ahead: int
    days_with_slots: int
    #: Последний день, на который расписание разложено — то самое «до 19 октября».
    horizon_date: date


async def _trainer_defaults(session: AsyncSession, trainer_id: int) -> tuple[int, int | None]:
    """Длительность занятия и площадка по умолчанию — ровно то, что тренер уже выбрал."""
    r = await session.execute(
        text(
            """
            SELECT p.session_duration_minutes, t.primary_arena_id
            FROM trainers t
            LEFT JOIN trainer_profiles p ON p.trainer_id = t.id
            WHERE t.id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    row = r.fetchone()
    if row is None:
        return DEFAULT_SESSION_DURATION_MINUTES, None
    duration = int(row[0]) if row[0] else DEFAULT_SESSION_DURATION_MINUTES
    arena_id = int(row[1]) if row[1] is not None else None
    return duration, arena_id


async def apply_trainer_first_hours_preset(
    session: AsyncSession,
    trainer_id: int,
    preset_key: str,
    *,
    today: date | None = None,
) -> FirstHoursResult:
    """
    Разложить пресет в недельный шаблон и две недели слотов.

    Поднимает ``QuickSetupError`` с текстом для тренера, когда часы пресета не ложатся на
    площадку (закрыта в это время, своя сетка, фиксированная длительность занятия). Это не
    сбой: экран в таком случае предлагает выбрать время самому в расписании.
    """
    preset = FIRST_HOURS_PRESETS.get(str(preset_key or "").strip())
    if preset is None:
        raise QuickSetupError("Неизвестный вариант времени.")

    duration_minutes, arena_id = await _trainer_defaults(session, trainer_id)
    days = [
        QuickSetupDay(day_of_week=dow, hours=preset.hours, arena_id=arena_id)
        for dow in preset.days
    ]

    result = await run_trainer_quick_setup(
        session,
        trainer_id,
        service_ids=[],
        days=days,
        duration_minutes=duration_minutes,
        city_id=None,
        today=today,
    )

    base = today or date.today()
    week_start = base - timedelta(days=base.weekday())
    horizon = week_start + timedelta(weeks=QUICK_SETUP_WEEKS) - timedelta(days=1)
    return FirstHoursResult(
        open_slots_ahead=result.open_slots_ahead,
        days_with_slots=result.days_with_slots,
        horizon_date=horizon,
    )
