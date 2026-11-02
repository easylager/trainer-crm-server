"""Two parallel writers for one trainer/day must not leave identical twin slots (prod incident 2026-11-03)."""
import asyncio
import os
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.application.trainer_schedule_use_cases import replace_slots_for_day

DAY = date(2026, 11, 3)
STARTS = {12 * 60 + 15, 13 * 60 + 15, 14 * 60 + 15, 15 * 60 + 15}


class _RaceSession(AsyncSession):
    """Holds each writer at its first slot INSERT until the other one has also read «no slots yet».

    Makes the race deterministic: without a per-trainer lock the second writer arrives while the first
    waits (both read an empty day, both insert). With the lock the second never gets here, the wait
    times out and the writers simply run one after another.
    """

    arrived = 0
    gate: asyncio.Event | None = None

    async def execute(self, statement, *args, **kwargs):
        if str(statement).lstrip().startswith("INSERT INTO slots") and not getattr(self, "_held", False):
            self._held = True
            cls = _RaceSession
            cls.arrived += 1
            if cls.arrived >= 2:
                cls.gate.set()
            try:
                await asyncio.wait_for(cls.gate.wait(), timeout=0.7)
            except asyncio.TimeoutError:
                pass
        return await super().execute(statement, *args, **kwargs)


@pytest.mark.asyncio
async def test_parallel_day_saves_do_not_duplicate_slots() -> None:
    """Double tap on «Готово»: both requests read «no slots yet», both insert."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    factory = async_sessionmaker(engine, class_=_RaceSession, expire_on_commit=False)
    _RaceSession.arrived = 0
    _RaceSession.gate = asyncio.Event()
    async with factory() as s:
        r = await s.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
        (trainer_id,) = r.fetchone()
        await s.commit()
    try:

        async def save() -> None:
            async with factory() as s:
                await replace_slots_for_day(s, trainer_id, DAY, STARTS, 45, per_slot_duration={m: 45 for m in STARTS})

        await asyncio.gather(save(), save())

        async with factory() as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT start_time, COUNT(*) FROM slots WHERE trainer_id = :t GROUP BY start_time"
                    ),
                    {"t": trainer_id},
                )
            ).fetchall()
        assert len(rows) == len(STARTS)
        assert all(n == 1 for _, n in rows), rows
    finally:
        async with factory() as s:
            await s.execute(text("DELETE FROM slots WHERE trainer_id = :t"), {"t": trainer_id})
            await s.execute(text("DELETE FROM trainers WHERE id = :t"), {"t": trainer_id})
            await s.commit()
        await engine.dispose()


@pytest.mark.asyncio
async def test_unique_index_rejects_identical_live_slot_but_allows_cancelled(db_session: AsyncSession) -> None:
    r = await db_session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    ins = text(
        "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity, arena_id, is_online) "
        "VALUES (:t, :d, '12:15', '13:00', :st, 1, NULL, false)"
    )
    await db_session.execute(ins, {"t": trainer_id, "d": DAY, "st": "cancelled"})
    await db_session.execute(ins, {"t": trainer_id, "d": DAY, "st": "available"})
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(ins, {"t": trainer_id, "d": DAY, "st": "booked"})
