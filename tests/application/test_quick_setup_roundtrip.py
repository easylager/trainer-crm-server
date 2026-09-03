"""
TASK-021: экран онбординга не должен разрушать то, что он не показывал.

Экран переоткрываем: у вернувшегося тренера он называется «Ваше расписание» и кнопка на нём —
«Сохранить». То есть это второй, упрощённый редактор поверх того же шаблона недели, что и
раздел «Расписание». До этой правки одно нажатие «Сохранить» молча теряло минуты слотов,
вторую площадку внутри дня и все групповые строки шаблона.
"""
from __future__ import annotations

from datetime import time

import pytest
from sqlalchemy import text

from src.application.trainer_quick_setup_use_cases import (
    QuickSetupDay,
    QuickSetupSlot,
    parse_quick_setup_days,
    run_trainer_quick_setup,
)


async def _new_trainer(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    tid = int(r.fetchone()[0])
    await db_session.commit()
    return tid


async def _city(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if row:
        return int(row[0])
    r = await db_session.execute(
        text("INSERT INTO cities (name) VALUES ('Тестгород') RETURNING id")
    )
    cid = int(r.fetchone()[0])
    await db_session.commit()
    return cid


async def _arena(db_session, city_id: int, name: str) -> int:
    r = await db_session.execute(
        text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, :n, true) RETURNING id"),
        {"c": city_id, "n": name},
    )
    aid = int(r.fetchone()[0])
    await db_session.commit()
    return aid


async def _service(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("need services in DB")
    return int(row[0])


async def _template(db_session, trainer_id: int) -> list[tuple[int, str, int, int, int | None]]:
    """(day_of_week, start_time, duration, capacity, arena_id) — весь шаблон тренера."""
    r = await db_session.execute(
        text(
            "SELECT day_of_week, start_time, duration_minutes, capacity, arena_id "
            "FROM trainer_schedule_templates WHERE trainer_id = :t "
            "ORDER BY day_of_week, start_time"
        ),
        {"t": trainer_id},
    )
    return [
        (int(x[0]), str(x[1]), int(x[2]), int(x[3]), int(x[4]) if x[4] is not None else None)
        for x in r.fetchall()
    ]


async def _add_row(
    db_session,
    trainer_id: int,
    *,
    dow: int,
    start: str,
    duration: int = 60,
    capacity: int = 1,
    arena_id: int | None = None,
    service_id: int | None = None,
) -> None:
    await db_session.execute(
        text(
            "INSERT INTO trainer_schedule_templates "
            "(trainer_id, day_of_week, start_time, duration_minutes, capacity, service_id, arena_id) "
            "VALUES (:t, :d, :s, :dur, :cap, :svc, :a)"
        ),
        {
            "t": trainer_id,
            "d": dow,
            "s": time.fromisoformat(start),
            "dur": duration,
            "cap": capacity,
            "svc": service_id,
            "a": arena_id,
        },
    )
    await db_session.commit()


def _as_payload(rows) -> list[dict]:
    """Шаблон → payload экрана, как его отдаёт GET и присылает обратно POST."""
    by_day: dict[int, list[dict]] = {}
    for dow, start, dur, cap, arena_id in rows:
        if cap != 1:
            continue
        h, m, _ = start.split(":")
        by_day.setdefault(dow, []).append(
            {
                "start_minute": int(h) * 60 + int(m),
                "duration_minutes": dur,
                "arena_id": arena_id,
            }
        )
    return [{"day_of_week": d, "slots": by_day[d]} for d in sorted(by_day)]


@pytest.mark.asyncio
async def test_minutes_survive_a_save_that_changed_nothing(app_use_test_db, db_session) -> None:
    """AC-001. Слот в 13:25 остаётся 13:25, а не превращается в 13:00."""
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    await _add_row(db_session, trainer_id, dow=0, start="13:25:00")
    before = await _template(db_session, trainer_id)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=parse_quick_setup_days(_as_payload(before)),
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == before


@pytest.mark.asyncio
async def test_group_rows_survive_a_save(app_use_test_db, db_session) -> None:
    """AC-002. Онбординг не умеет рисовать групповые занятия — значит и удалять их не вправе."""
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    await _add_row(db_session, trainer_id, dow=0, start="07:00:00")
    await _add_row(
        db_session, trainer_id, dow=0, start="10:00:00", capacity=8, service_id=service_id
    )
    await _add_row(
        db_session, trainer_id, dow=4, start="19:00:00", capacity=12, service_id=service_id
    )
    before = await _template(db_session, trainer_id)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=parse_quick_setup_days(_as_payload(before)),
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == before


@pytest.mark.asyncio
async def test_group_row_survives_a_day_the_trainer_cleared(app_use_test_db, db_session) -> None:
    """EDGE-001. Для онбординга пятница пуста, но её групповая строка — не его собственность."""
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    await _add_row(db_session, trainer_id, dow=0, start="07:00:00")
    await _add_row(
        db_session, trainer_id, dow=4, start="19:00:00", capacity=12, service_id=service_id
    )

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=0, slots=(QuickSetupSlot(start_minute=7 * 60),))],
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == [
        (0, "07:00:00", 60, 1, None),
        (4, "19:00:00", 60, 12, None),
    ]


@pytest.mark.asyncio
async def test_two_arenas_in_one_day_survive_a_save(app_use_test_db, db_session) -> None:
    """AC-003. День, собранный в «Расписании» из двух площадок, переживает «Сохранить»."""
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A")
    arena_b = await _arena(db_session, city_id, "Каток B")
    await _add_row(db_session, trainer_id, dow=0, start="07:00:00", arena_id=arena_a)
    await _add_row(db_session, trainer_id, dow=0, start="19:00:00", arena_id=arena_b)
    before = await _template(db_session, trainer_id)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=parse_quick_setup_days(_as_payload(before)),
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == before


@pytest.mark.asyncio
async def test_unchecking_one_cell_removes_exactly_that_row(app_use_test_db, db_session) -> None:
    """AC-004. Снятая отметка удаляет свою строку и только её."""
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A")
    await _add_row(db_session, trainer_id, dow=0, start="07:00:00", arena_id=arena_a)
    await _add_row(db_session, trainer_id, dow=0, start="13:25:00", arena_id=arena_a)
    await _add_row(db_session, trainer_id, dow=0, start="19:00:00", arena_id=arena_a)

    kept = [r for r in await _template(db_session, trainer_id) if r[1] != "19:00:00"]
    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=parse_quick_setup_days(_as_payload(kept)),
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == kept


@pytest.mark.asyncio
async def test_new_individual_slot_cannot_be_laid_over_a_group_class(
    app_use_test_db, db_session
) -> None:
    """
    EDGE-002. Групповую строку мы больше не удаляем — значит она обязана участвовать
    в проверке пересечений, иначе тренер окажется в двух местах одновременно.
    """
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    await _add_row(
        db_session, trainer_id, dow=0, start="10:00:00", capacity=8, service_id=service_id
    )

    with pytest.raises(ValueError, match="пересекается"):
        await run_trainer_quick_setup(
            db_session,
            trainer_id,
            service_ids=[service_id],
            days=[
                QuickSetupDay(
                    day_of_week=0,
                    slots=(QuickSetupSlot(start_minute=10 * 60 + 30, duration_minutes=60),),
                )
            ],
            duration_minutes=60,
        )


@pytest.mark.asyncio
async def test_legacy_hours_payload_still_saves(app_use_test_db, db_session) -> None:
    """
    Mini App, оставшийся на прошлом скрипте, шлёт «часы». Он должен продолжать работать —
    и, что важнее, больше не стирать групповые строки, даже не зная о них.
    """
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    await _add_row(
        db_session, trainer_id, dow=2, start="18:00:00", capacity=10, service_id=service_id
    )

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=parse_quick_setup_days([{"day_of_week": 0, "hours": [7, 8]}]),
        duration_minutes=60,
    )

    assert await _template(db_session, trainer_id) == [
        (0, "07:00:00", 60, 1, None),
        (0, "08:00:00", 60, 1, None),
        (2, "18:00:00", 60, 10, None),
    ]


@pytest.mark.asyncio
async def test_hour_grid_and_carried_slots_arrive_together_for_one_day(
    app_use_test_db, db_session
) -> None:
    """
    Так экран и шлёт: часть дня — сетка часами, остальное — перенесённые слоты минутами.
    Пойман живым прогоном в браузере: первая версия парсера считала это ошибкой клиента
    и отвечала 400, из-за чего вернувшийся тренер вообще не мог сохраниться.
    """
    trainer_id = await _new_trainer(db_session)
    service_id = await _service(db_session)
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A")
    arena_b = await _arena(db_session, city_id, "Каток B")

    days = parse_quick_setup_days(
        [
            {"day_of_week": 1, "hours": [9], "arena_id": arena_a},
            {
                "day_of_week": 1,
                "slots": [
                    {"start_minute": 13 * 60 + 25, "duration_minutes": 45, "arena_id": arena_a},
                    {"start_minute": 19 * 60, "duration_minutes": 45, "arena_id": arena_b},
                ],
            },
        ]
    )
    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=days,
        duration_minutes=45,
    )

    assert await _template(db_session, trainer_id) == [
        (1, "09:00:00", 45, 1, arena_a),
        (1, "13:25:00", 45, 1, arena_a),
        (1, "19:00:00", 45, 1, arena_b),
    ]
