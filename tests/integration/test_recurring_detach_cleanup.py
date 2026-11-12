"""TASK-396: снятие «постоянного клиента» не оставляет пустых окон и мусора.

- окно, которое цикл автозаписи создал сам, удаляется при снятии правила / обрезке за горизонтом;
- окно тренера, которое цикл лишь переиспользовал, остаётся ``available``;
- удаление клиента из списка закрывает его правила — цикл больше не ставит ему записи;
- клиенту ставится ровно одно сообщение на снятое правило (sandbox / без Telegram — ни одного);
- снятие — одна транзакция: сбой посередине оставляет всё как было.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import detach_trainer_client_from_roster_miniapp
from src.application.recurring_use_cases import (
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    list_pending_recurring_removed_notices,
    maintain_recurring_horizon,
    materialize_recurring_horizon,
    prune_recurring_bookings_beyond_horizon,
    this_week_monday,
)
from src.bot.trainer_cancel_client_notify import process_recurring_removed_notices_batch
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

DOW = 1  # Tuesday
ST = time(10, 0)
ET = time(11, 0)


async def _seed_trainer(session: AsyncSession) -> int:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    trainer_id = int(r.scalar_one())
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age) "
            "VALUES (:tid, 'Рег', 'Тренер', 30)"
        ),
        {"tid": trainer_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    r = await session.execute(text("SELECT id FROM subscription_plans ORDER BY id LIMIT 1"))
    plan_id = r.scalar()
    if plan_id is None:
        pytest.skip("need subscription_plans in DB")
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO trainer_subscriptions
                (trainer_id, plan_id, tier, billing_period_months, started_at, expires_at, status)
            VALUES (:tid, :pid, 'crm', 1, :st, :exp, 'active')
            """
        ),
        {"tid": trainer_id, "pid": plan_id, "st": now, "exp": now + timedelta(days=400)},
    )
    await session.commit()
    return trainer_id


async def _seed_client(
    session: AsyncSession, trainer_id: int, *, sandbox: bool = False, telegram: bool = True
) -> int:
    tg = unique_test_telegram_id()
    phone, phone_n = belarus_test_phone(tg)
    r = await session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, last_name, phone, phone_normalized, is_sandbox)
            VALUES (:tg, 'Постоянный', 'Клиент', :phone, :pn, :sb)
            RETURNING id
            """
        ),
        {"tg": tg if telegram else None, "phone": phone, "pn": phone_n, "sb": sandbox},
    )
    client_id = int(r.scalar_one())
    if telegram:
        # Roster detach touches client_trainer_edges, keyed on the bot session row.
        await session.execute(
            text("INSERT INTO client_sessions (telegram_id, state) VALUES (:tg, 'idle')"),
            {"tg": tg},
        )
    await session.execute(
        text("INSERT INTO trainer_client_roster (trainer_id, client_id) VALUES (:tid, :cid)"),
        {"tid": trainer_id, "cid": client_id},
    )
    await session.commit()
    return client_id


def _week_date(i: int) -> date:
    return this_week_monday() + timedelta(days=7 * i + DOW)


async def _rule_with_three_weeks(session: AsyncSession, trainer_id: int, client_id: int) -> int:
    rid = await create_recurring_client_slot(session, trainer_id, client_id, DOW, ST, ET)
    assert rid
    # Weeks 1..3 — never in the past, whatever day/time the test runs.
    created = await materialize_recurring_horizon(
        session, trainer_id, horizon_weeks=3, recurring_ids=[rid], min_week_index=1
    )
    assert created == 3
    return int(rid)


async def _slots_on_rule_dates(session: AsyncSession, trainer_id: int) -> dict[date, tuple[int, str]]:
    r = await session.execute(
        text(
            """
            SELECT slot_date, id, status FROM slots
            WHERE trainer_id = :tid AND slot_date = ANY(:dates) AND start_time = :st
            """
        ),
        {"tid": trainer_id, "dates": [_week_date(i) for i in (1, 2, 3)], "st": ST},
    )
    return {row[0]: (int(row[1]), str(row[2])) for row in r.fetchall()}


async def _rule_row(session: AsyncSession, rid: int) -> tuple[str, object, object]:
    r = await session.execute(
        text(
            "SELECT status, client_notice_queued_at, client_notice_sent_at "
            "FROM recurring_client_slots WHERE id = :id"
        ),
        {"id": rid},
    )
    row = r.fetchone()
    return str(row[0]), row[1], row[2]


async def _active_bookings(session: AsyncSession, trainer_id: int, client_id: int) -> int:
    r = await session.execute(
        text(
            "SELECT COUNT(*) FROM bookings WHERE trainer_id = :tid AND client_id = :cid "
            "AND status IN ('pending', 'confirmed')"
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_remove_rule_drops_windows_created_by_cycle(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)

    slots = await _slots_on_rule_dates(db_session, trainer_id)
    assert len(slots) == 3
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM slots WHERE created_for_recurring_client_slot_id = :rid"),
        {"rid": rid},
    )
    assert int(r.scalar_one()) == 3

    ok, removed = await cancel_recurring_client_slot(db_session, trainer_id, rid)
    assert ok is True
    assert removed == 3
    assert await _slots_on_rule_dates(db_session, trainer_id) == {}
    status, queued, _ = await _rule_row(db_session, rid)
    assert status == "cancelled"
    assert queued is not None
    assert await _active_bookings(db_session, trainer_id, client_id) == 0


@pytest.mark.asyncio
async def test_remove_rule_keeps_trainer_window_reused_by_cycle(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status, capacity)
            VALUES (:tid, :d, :st, :et, 'available', 1)
            RETURNING id
            """
        ),
        {"tid": trainer_id, "d": _week_date(1), "st": ST, "et": ET},
    )
    template_slot_id = int(r.scalar_one())
    await db_session.commit()

    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)
    slots = await _slots_on_rule_dates(db_session, trainer_id)
    assert slots[_week_date(1)] == (template_slot_id, "booked")

    ok, removed = await cancel_recurring_client_slot(db_session, trainer_id, rid)
    assert ok and removed == 3
    slots = await _slots_on_rule_dates(db_session, trainer_id)
    assert slots == {_week_date(1): (template_slot_id, "available")}


@pytest.mark.asyncio
async def test_prune_beyond_horizon_drops_cycle_window(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)

    # Horizon shrinks to 2 weeks: weeks 2 and 3 are beyond it.
    pruned = await prune_recurring_bookings_beyond_horizon(
        db_session, trainer_id, horizon_weeks=2, recurring_ids=[rid]
    )
    assert pruned == 2
    slots = await _slots_on_rule_dates(db_session, trainer_id)
    assert set(slots) == {_week_date(1)}
    assert slots[_week_date(1)][1] == "booked"
    status, queued, _ = await _rule_row(db_session, rid)
    assert status == "active"
    assert queued is None


@pytest.mark.asyncio
async def test_roster_detach_closes_rule_and_stops_cycle(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)

    result = await detach_trainer_client_from_roster_miniapp(db_session, trainer_id, client_id)
    assert result is not None
    assert result["roster_removed"] is True
    assert result["recurring_removed"] == 1
    assert result["cancelled_upcoming_bookings"] == 3

    status, queued, _ = await _rule_row(db_session, rid)
    assert status == "cancelled"
    # Auto-bookings go silently with their windows; the client hears it once, per rule.
    assert queued is not None
    assert await _slots_on_rule_dates(db_session, trainer_id) == {}

    out = await maintain_recurring_horizon(db_session, trainer_id, horizon_weeks=3, min_week_index=1)
    assert out["created"] == 0
    assert await _active_bookings(db_session, trainer_id, client_id) == 0


@pytest.mark.asyncio
async def test_remove_rule_queues_exactly_one_client_notice(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)

    await cancel_recurring_client_slot(db_session, trainer_id, rid)

    pending = [p for p in await list_pending_recurring_removed_notices(db_session) if p["id"] == rid]
    assert len(pending) == 1
    r = await db_session.execute(
        text(
            """
            SELECT COUNT(*) FROM booking_cancel_notifications n
            JOIN bookings b ON b.id = n.booking_id
            WHERE b.recurring_client_slot_id = :rid
            """
        ),
        {"rid": rid},
    )
    assert int(r.scalar_one()) == 0

    bot = AsyncMock()
    with patch(
        "src.bot.trainer_cancel_client_notify.list_pending_recurring_removed_notices",
        new=AsyncMock(return_value=pending),
    ):
        await process_recurring_removed_notices_batch(bot, db_session)
        # A second drain (or a parallel worker) must not resend the same rule notice.
        await process_recurring_removed_notices_batch(bot, db_session)
    assert bot.send_message.await_count == 1
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert "Постоянное время снято" in sent_text
    assert "Вт · 10:00–11:00" in sent_text
    _, _, sent_at = await _rule_row(db_session, rid)
    assert sent_at is not None
    assert [p for p in await list_pending_recurring_removed_notices(db_session) if p["id"] == rid] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("sandbox,telegram", [(True, True), (False, False)])
async def test_remove_rule_no_notice_for_sandbox_or_no_telegram(
    db_session: AsyncSession, sandbox: bool, telegram: bool
) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id, sandbox=sandbox, telegram=telegram)
    rid = await create_recurring_client_slot(db_session, trainer_id, client_id, DOW, ST, ET)
    assert rid
    ok, _ = await cancel_recurring_client_slot(db_session, trainer_id, int(rid))
    assert ok
    status, queued, _ = await _rule_row(db_session, int(rid))
    assert status == "cancelled"
    assert queued is None


@pytest.mark.asyncio
async def test_rollback_of_new_rule_is_silent(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await create_recurring_client_slot(db_session, trainer_id, client_id, DOW, ST, ET)
    ok, _ = await cancel_recurring_client_slot(db_session, trainer_id, int(rid), notify_client=False)
    assert ok
    _, queued, _ = await _rule_row(db_session, int(rid))
    assert queued is None


@pytest.mark.asyncio
async def test_remove_rule_is_atomic(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)

    from src.application import recurring_use_cases as ruc

    real = ruc.delete_emptied_recurring_created_slot
    calls = {"n": 0}

    async def _boom_on_second(session, tid, sid):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return await real(session, tid, sid)

    with patch.object(ruc, "delete_emptied_recurring_created_slot", new=_boom_on_second):
        with pytest.raises(RuntimeError):
            await cancel_recurring_client_slot(db_session, trainer_id, rid)

    status, queued, _ = await _rule_row(db_session, rid)
    assert status == "active"
    assert queued is None
    assert await _active_bookings(db_session, trainer_id, client_id) == 3
    assert len(await _slots_on_rule_dates(db_session, trainer_id)) == 3
