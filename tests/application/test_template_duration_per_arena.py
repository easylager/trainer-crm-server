"""
TASK-022: длительность строки шаблона проверяется против пресета ЕЁ арены.

Реальный кейс: тренер работает на двух катках, один продаёт только 60-минутные слоты,
другой — только 45-минутные. До этой правки ``replace_templates_for_day`` резолвил один
пресет на весь вызов — по ``primary_arena_id`` тренера — и вторая арена не сохранялась
вообще, с сообщением, которое не называло ни площадку, ни требуемое значение.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_schedule_use_cases import replace_templates_for_day


async def _new_trainer(db_session, *, primary_arena_id: int | None = None) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status, primary_arena_id) VALUES ('active', :a) RETURNING id"),
        {"a": primary_arena_id},
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


async def _arena(db_session, city_id: int, name: str, *, fixed_duration: int | None = None) -> int:
    r = await db_session.execute(
        text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, :n, true) RETURNING id"),
        {"c": city_id, "n": name},
    )
    aid = int(r.fetchone()[0])
    if fixed_duration is not None:
        await db_session.execute(
            text(
                """
                INSERT INTO arena_schedule_presets
                    (arena_id, grid_kind, minute_offset, hour_start, hour_end, slot_duration_minutes)
                VALUES (:aid, 'quarter_15', 0, 6, 23, :dur)
                """
            ),
            {"aid": aid, "dur": fixed_duration},
        )
    await db_session.commit()
    return aid


async def _link(db_session, trainer_id: int, arena_id: int) -> None:
    await db_session.execute(
        text(
            "INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:t, :a) "
            "ON CONFLICT DO NOTHING"
        ),
        {"t": trainer_id, "a": arena_id},
    )
    await db_session.commit()


async def _rows(db_session, trainer_id: int, dow: int) -> list[tuple[str, int, int | None]]:
    r = await db_session.execute(
        text(
            "SELECT start_time, duration_minutes, arena_id FROM trainer_schedule_templates "
            "WHERE trainer_id = :t AND day_of_week = :d ORDER BY start_time"
        ),
        {"t": trainer_id, "d": dow},
    )
    return [(str(x[0]), int(x[1]), int(x[2]) if x[2] is not None else None) for x in r.fetchall()]


@pytest.mark.asyncio
async def test_two_arenas_with_different_fixed_durations_save_in_one_day(
    app_use_test_db, db_session
) -> None:
    """AC-001. Главный кейс задачи: арена A фиксирует 60, арена B — 45, день один."""
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A", fixed_duration=60)
    arena_b = await _arena(db_session, city_id, "Каток B", fixed_duration=45)
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)
    await _link(db_session, trainer_id, arena_b)

    await replace_templates_for_day(
        db_session,
        trainer_id,
        0,
        {7 * 60: 1, 19 * 60: 1},
        60,
        minute_to_arena_id={7 * 60: arena_a, 19 * 60: arena_b},
        minute_to_duration={7 * 60: 60, 19 * 60: 45},
    )

    assert await _rows(db_session, trainer_id, 0) == [
        ("07:00:00", 60, arena_a),
        ("19:00:00", 45, arena_b),
    ]


@pytest.mark.asyncio
async def test_row_duration_is_checked_against_its_own_arena_not_the_primary(
    app_use_test_db, db_session
) -> None:
    """AC-002. Основная арена тренера фиксирует 45 — это не делает 45 законными на арене B."""
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A", fixed_duration=45)
    arena_b = await _arena(db_session, city_id, "Каток B", fixed_duration=60)
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)
    await _link(db_session, trainer_id, arena_b)

    with pytest.raises(ValueError):
        await replace_templates_for_day(
            db_session,
            trainer_id,
            0,
            {7 * 60: 1, 19 * 60: 1},
            45,
            minute_to_arena_id={7 * 60: arena_a, 19 * 60: arena_b},
            minute_to_duration={7 * 60: 45, 19 * 60: 45},  # 45 на арене, которая требует 60
        )


@pytest.mark.asyncio
async def test_error_names_the_arena_the_duration_and_the_time(app_use_test_db, db_session) -> None:
    """AC-003. Сообщение должно быть починябельным: какая площадка, сколько нужно, где."""
    city_id = await _city(db_session)
    arena_b = await _arena(db_session, city_id, "Ледовый Полюс", fixed_duration=90)
    trainer_id = await _new_trainer(db_session)
    await _link(db_session, trainer_id, arena_b)

    with pytest.raises(ValueError) as exc:
        await replace_templates_for_day(
            db_session,
            trainer_id,
            0,
            {19 * 60: 1},
            60,
            minute_to_arena_id={19 * 60: arena_b},
        )
    msg = str(exc.value)
    assert "Ледовый Полюс" in msg
    assert "90" in msg
    assert "19:00" in msg


@pytest.mark.asyncio
async def test_row_without_arena_still_uses_the_trainer_preset(app_use_test_db, db_session) -> None:
    """AC-004. arena_id IS NULL уже означает «арена тренера по умолчанию» — валидация читает так же."""
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A", fixed_duration=60)
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)

    with pytest.raises(ValueError):
        await replace_templates_for_day(db_session, trainer_id, 0, {7 * 60: 1}, 45)

    # arena_id остаётся NULL: строка без площадки резолвится на арену тренера при
    # материализации слотов, и валидация обязана читать её так же.
    await replace_templates_for_day(db_session, trainer_id, 0, {7 * 60: 1}, 60)
    assert await _rows(db_session, trainer_id, 0) == [("07:00:00", 60, None)]


@pytest.mark.asyncio
async def test_group_row_is_checked_against_its_group_arena(app_use_test_db, db_session) -> None:
    """EDGE-002. Групповая строка живёт на своей площадке — проверяем её пресетом."""
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A", fixed_duration=60)
    arena_b = await _arena(db_session, city_id, "Каток B", fixed_duration=90)
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)
    await _link(db_session, trainer_id, arena_b)
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("need services in DB")
    service_id = int(row[0])

    with pytest.raises(ValueError):
        await replace_templates_for_day(
            db_session,
            trainer_id,
            0,
            {10 * 60: 8},
            60,  # пресет группы (арена B) требует 90
            minute_to_service_id={10 * 60: service_id},
            group_arena_id=arena_b,
        )

    await replace_templates_for_day(
        db_session,
        trainer_id,
        0,
        {10 * 60: 8},
        90,
        minute_to_service_id={10 * 60: service_id},
        group_arena_id=arena_b,
    )
    assert await _rows(db_session, trainer_id, 0) == [("10:00:00", 90, arena_b)]


@pytest.mark.asyncio
async def test_empty_day_does_not_validate_a_duration_nothing_uses(
    app_use_test_db, db_session
) -> None:
    """
    Пустой день не должен проверять длительность: применять её не к чему.

    Это тот же класс бага, что обходит ``empty_day_duration`` в онбординге
    (`trainer_quick_setup_use_cases.py`): раньше очистка дня у тренера, чья основная
    арена фиксирует длительность, падала, если вызывающий передал другое число.
    """
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A", fixed_duration=90)
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)

    await replace_templates_for_day(db_session, trainer_id, 0, {}, 60)
    assert await _rows(db_session, trainer_id, 0) == []


@pytest.mark.asyncio
async def test_off_grid_starts_are_still_allowed(app_use_test_db, db_session) -> None:
    """
    AC-005 / Q-001. Точные слоты вне сетки — заявленная возможность раздела «Расписание»,
    а не лазейка. Правка длительности не должна её закрыть.
    """
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток со своей сеткой")
    trainer_id = await _new_trainer(db_session, primary_arena_id=arena_a)
    await _link(db_session, trainer_id, arena_a)

    await replace_templates_for_day(
        db_session,
        trainer_id,
        0,
        {13 * 60 + 25: 1},
        60,
        minute_to_arena_id={13 * 60 + 25: arena_a},
    )
    assert await _rows(db_session, trainer_id, 0) == [("13:25:00", 60, arena_a)]


@pytest.mark.asyncio
async def test_overlap_error_names_both_conflicting_slots_and_venues(
    app_use_test_db, db_session
) -> None:
    """
    TASK-023 AC-004. Мультиарена внутри дня делает такие конфликты частыми: тренер ставит
    вечерний слот на арене B, не заметив, что он наезжает на утренний слот арены A.
    Сообщение обязано назвать оба времени и обе площадки, а не только факт пересечения.
    """
    city_id = await _city(db_session)
    arena_a = await _arena(db_session, city_id, "Каток A")
    arena_b = await _arena(db_session, city_id, "Каток B")
    trainer_id = await _new_trainer(db_session)
    await _link(db_session, trainer_id, arena_a)
    await _link(db_session, trainer_id, arena_b)

    await replace_templates_for_day(
        db_session, trainer_id, 0, {7 * 60: 1}, 60, minute_to_arena_id={7 * 60: arena_a}
    )

    with pytest.raises(ValueError) as exc:
        await replace_templates_for_day(
            db_session,
            trainer_id,
            0,
            {7 * 60: 1, 7 * 60 + 30: 1},
            60,
            minute_to_arena_id={7 * 60: arena_a, 7 * 60 + 30: arena_b},
        )
    msg = str(exc.value)
    assert "07:00" in msg and "08:00" in msg
    assert "Каток A" in msg and "Каток B" in msg
