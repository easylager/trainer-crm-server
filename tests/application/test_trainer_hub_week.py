"""Неделя на главной тренера: занятия по дням и свободные окна (TASK-314, волна 2)."""
from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from sqlalchemy import text

from src.application.trainer_hub_week import hub_week_summary


async def _slot(s, trainer_id: int, d: date, start: time, status: str = "available") -> int:
    r = await s.execute(
        text(
            "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status) "
            "VALUES (:t, :d, :st, :en, :status) RETURNING id"
        ),
        {"t": trainer_id, "d": d, "st": start, "en": time(start.hour + 1, start.minute), "status": status},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_week_counts_sessions_and_future_free_windows(db_session) -> None:
    s = db_session
    tid = int((await s.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))).scalar_one())
    cid = int((await s.execute(text("INSERT INTO clients (first_name) VALUES ('Мария') RETURNING id"))).scalar_one())
    svc = int((await s.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))).scalar_one())
    today = date.today()
    tomorrow = today + timedelta(days=1)
    booked = await _slot(s, tid, tomorrow, time(17, 15), "booked")
    await _slot(s, tid, tomorrow, time(18, 15))
    await _slot(s, tid, tomorrow, time(19, 15))
    await _slot(s, tid, today + timedelta(days=9), time(18, 15))  # за пределами недели
    await s.execute(
        text(
            "INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status) "
            "VALUES (:s, :t, :c, :svc, 'pending')"
        ),
        {"s": booked, "t": tid, "c": cid, "svc": svc},
    )

    week = await hub_week_summary(s, tid, today)

    assert len(week["days"]) == 7
    day = next(d for d in week["days"] if d["date"] == tomorrow.isoformat())
    assert day["sessions"] == 1 and day["pending"] == 1
    assert day["free_times"] == ["18:15", "19:15"]
    assert week["sessions"] == 1 and week["free"] == 2
