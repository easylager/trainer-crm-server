"""
Онбординг v2: тумблер «одна / несколько площадок».

Реальный кейс, из которого выросла эта задача: тренер работает на ТЦ Замок, где слоты
начинаются в :15 каждого часа, а не в :00 — обычная почасовая сетка онбординга там
буквально создала бы невалидное расписание. И второй кейс: тренер работает на двух
аренах в разные дни недели, и клиенту, записавшемуся по ссылке, нужно точно знать,
куда идти — значит арена должна быть известна уже в момент, когда генерируются слоты.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_quick_setup_use_cases import (
    QuickSetupDay,
    QuickSetupError,
    parse_quick_setup_days,
    run_trainer_quick_setup,
)


async def _new_trainer(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
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


async def _set_hourly_preset(db_session, arena_id: int, *, minute_offset: int, hour_start: int, hour_end: int, fixed_duration: int | None = None) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO arena_schedule_presets
                (arena_id, grid_kind, minute_offset, hour_start, hour_end, slot_duration_minutes)
            VALUES (:aid, 'hourly_minute', :mo, :h0, :h1, :dur)
            ON CONFLICT (arena_id) DO UPDATE SET
                grid_kind = EXCLUDED.grid_kind,
                minute_offset = EXCLUDED.minute_offset,
                hour_start = EXCLUDED.hour_start,
                hour_end = EXCLUDED.hour_end,
                slot_duration_minutes = EXCLUDED.slot_duration_minutes
            """
        ),
        {"aid": arena_id, "mo": minute_offset, "h0": hour_start, "h1": hour_end, "dur": fixed_duration},
    )
    await db_session.commit()


async def _any_service_id(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if not row:
        pytest.skip("need services in DB")
    return int(row[0])


# ---------------------------------------------------------------------------
# parse_quick_setup_days: arena_id extraction, «last one wins per day»
# ---------------------------------------------------------------------------


def test_parse_reads_arena_id_per_day() -> None:
    days = parse_quick_setup_days(
        [
            {"day_of_week": 0, "hours": [7], "arena_id": 5},
            {"day_of_week": 1, "hours": [9]},  # без арены — по-прежнему валидно
        ]
    )
    by_dow = {d.day_of_week: d for d in days}
    assert by_dow[0].arena_id == 5
    assert by_dow[1].arena_id is None


def test_parse_last_arena_wins_for_a_repeated_day() -> None:
    """UI шлёт по одному объекту на день на арена-таб; последний touch должен победить."""
    days = parse_quick_setup_days(
        [
            {"day_of_week": 0, "hours": [7], "arena_id": 5},
            {"day_of_week": 0, "hours": [7, 8], "arena_id": 9},
        ]
    )
    assert len(days) == 1
    assert days[0].arena_id == 9
    assert days[0].hours == (7, 8)


def test_parse_rejects_garbage_arena_id() -> None:
    with pytest.raises(QuickSetupError):
        parse_quick_setup_days([{"day_of_week": 0, "hours": [7], "arena_id": "not-a-number"}])
    with pytest.raises(QuickSetupError):
        parse_quick_setup_days([{"day_of_week": 0, "hours": [7], "arena_id": -1}])


# ---------------------------------------------------------------------------
# run_trainer_quick_setup: реальная сетка ТЦ Замок (:15, 10:00–22:00)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hourly_offset_arena_shifts_slots_off_the_hour(app_use_test_db, db_session) -> None:
    """Ровно кейс из ТЦ Замок: чипы «7, 18» на этой площадке означают 7:15 и 18:15, не 7:00/18:00."""
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "ТЦ Замок")
    await _set_hourly_preset(db_session, arena_id, minute_offset=15, hour_start=10, hour_end=22)
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=0, hours=(11, 18), arena_id=arena_id)],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text(
            "SELECT start_time, arena_id FROM trainer_schedule_templates "
            "WHERE trainer_id = :t ORDER BY start_time"
        ),
        {"t": trainer_id},
    )
    rows = [(str(x[0]), int(x[1])) for x in r.fetchall()]
    assert rows == [("11:15:00", arena_id), ("18:15:00", arena_id)]


@pytest.mark.asyncio
async def test_arena_out_of_hour_range_is_rejected_with_a_human_reason(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "ТЦ Замок")
    await _set_hourly_preset(db_session, arena_id, minute_offset=15, hour_start=10, hour_end=22)
    service_id = await _any_service_id(db_session)

    with pytest.raises(QuickSetupError, match="10:00.*22:00"):
        await run_trainer_quick_setup(
            db_session,
            trainer_id,
            service_ids=[service_id],
            days=[QuickSetupDay(day_of_week=0, hours=(7,), arena_id=arena_id)],  # арена открыта с 10
            duration_minutes=60,
        )


@pytest.mark.asyncio
async def test_arena_fixed_duration_overrides_the_trainers_chip(app_use_test_db, db_session) -> None:
    """Площадка с фиксированной длительностью важнее чипа, который выбрал тренер для этого дня."""
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Каток с фиксированным слотом")
    await _set_hourly_preset(
        db_session, arena_id, minute_offset=0, hour_start=8, hour_end=20, fixed_duration=90
    )
    service_id = await _any_service_id(db_session)

    result = await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=1, hours=(9,), arena_id=arena_id)],
        duration_minutes=45,  # тренер выбрал 45 — площадка требует 90
    )

    r = await db_session.execute(
        text("SELECT duration_minutes FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    assert r.scalar() == 90
    assert result.duration_minutes == 45, "глобальный ответ не переписывается — площадка переопределяет только свой день"


@pytest.mark.asyncio
async def test_arena_without_a_preset_row_behaves_like_no_arena(app_use_test_db, db_session) -> None:
    """Площадка без строки в arena_schedule_presets — обычная сетка, без сюрпризов."""
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Манеж")  # без пресета
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=2, hours=(9,), arena_id=arena_id)],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text("SELECT start_time, duration_minutes FROM trainer_schedule_templates WHERE trainer_id = :t"),
        {"t": trainer_id},
    )
    row = r.fetchone()
    assert str(row[0]) == "09:00:00"
    assert row[1] == 60


# ---------------------------------------------------------------------------
# Мультиарена: разные дни на разных площадках со своими сетками
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_arenas_on_different_days_keep_their_own_grids(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    zamok = await _arena(db_session, city_id, "ТЦ Замок")
    await _set_hourly_preset(db_session, zamok, minute_offset=15, hour_start=10, hour_end=22)
    manege = await _arena(db_session, city_id, "Манеж")  # стандартная сетка
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[
            QuickSetupDay(day_of_week=0, hours=(11,), arena_id=zamok),
            QuickSetupDay(day_of_week=1, hours=(9,), arena_id=manege),
        ],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text(
            "SELECT day_of_week, start_time, arena_id FROM trainer_schedule_templates "
            "WHERE trainer_id = :t ORDER BY day_of_week"
        ),
        {"t": trainer_id},
    )
    rows = {int(x[0]): (str(x[1]), int(x[2])) for x in r.fetchall()}
    assert rows[0] == ("11:15:00", zamok)
    assert rows[1] == ("09:00:00", manege)


@pytest.mark.asyncio
async def test_both_arenas_get_linked_to_the_trainer(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    a1 = await _arena(db_session, city_id, "Арена А")
    a2 = await _arena(db_session, city_id, "Арена Б")
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[
            QuickSetupDay(day_of_week=0, hours=(9,), arena_id=a1),
            QuickSetupDay(day_of_week=3, hours=(9,), arena_id=a2),
        ],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text("SELECT arena_id FROM trainer_arenas WHERE trainer_id = :t ORDER BY arena_id"),
        {"t": trainer_id},
    )
    assert sorted(int(x[0]) for x in r.fetchall()) == sorted([a1, a2])


@pytest.mark.asyncio
async def test_primary_arena_is_set_only_when_exactly_one_venue_is_used(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    a1 = await _arena(db_session, city_id, "Арена А")
    a2 = await _arena(db_session, city_id, "Арена Б")
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[
            QuickSetupDay(day_of_week=0, hours=(9,), arena_id=a1),
            QuickSetupDay(day_of_week=3, hours=(9,), arena_id=a2),
        ],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :t"), {"t": trainer_id}
    )
    assert r.scalar() is None, "две площадки — primary_arena_id остаётся неопределённым"


@pytest.mark.asyncio
async def test_primary_arena_is_set_for_a_single_venue_trainer(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    arena_id = await _arena(db_session, city_id, "Единственная арена")
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=0, hours=(9,), arena_id=arena_id)],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :t"), {"t": trainer_id}
    )
    assert r.scalar() == arena_id


@pytest.mark.asyncio
async def test_primary_arena_already_set_is_never_overwritten(app_use_test_db, db_session) -> None:
    """Тренер, у которого арена уже была назначена (сайт/оператор), не должен её потерять."""
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    original = await _arena(db_session, city_id, "Исходная арена")
    new_one = await _arena(db_session, city_id, "Новая арена")
    await db_session.execute(
        text("UPDATE trainers SET primary_arena_id = :a WHERE id = :t"),
        {"a": original, "t": trainer_id},
    )
    await db_session.commit()
    service_id = await _any_service_id(db_session)

    await run_trainer_quick_setup(
        db_session,
        trainer_id,
        service_ids=[service_id],
        days=[QuickSetupDay(day_of_week=0, hours=(9,), arena_id=new_one)],
        duration_minutes=60,
    )

    r = await db_session.execute(
        text("SELECT primary_arena_id FROM trainers WHERE id = :t"), {"t": trainer_id}
    )
    assert r.scalar() == original


@pytest.mark.asyncio
async def test_unknown_arena_id_is_rejected(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    service_id = await _any_service_id(db_session)

    with pytest.raises(QuickSetupError):
        await run_trainer_quick_setup(
            db_session,
            trainer_id,
            service_ids=[service_id],
            days=[QuickSetupDay(day_of_week=0, hours=(9,), arena_id=999_999_999)],
            duration_minutes=60,
        )


@pytest.mark.asyncio
async def test_inactive_arena_is_rejected(app_use_test_db, db_session) -> None:
    trainer_id = await _new_trainer(db_session)
    city_id = await _city(db_session)
    r = await db_session.execute(
        text("INSERT INTO arenas (city_id, name, is_active) VALUES (:c, 'Закрыта', false) RETURNING id"),
        {"c": city_id},
    )
    arena_id = int(r.fetchone()[0])
    await db_session.commit()
    service_id = await _any_service_id(db_session)

    with pytest.raises(QuickSetupError):
        await run_trainer_quick_setup(
            db_session,
            trainer_id,
            service_ids=[service_id],
            days=[QuickSetupDay(day_of_week=0, hours=(9,), arena_id=arena_id)],
            duration_minutes=60,
        )
