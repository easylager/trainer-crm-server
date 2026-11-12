"""TASK-396: снятие «постоянного клиента» не оставляет пустых окон и мусора.

- окно, которое цикл автозаписи создал сам, удаляется при снятии правила / обрезке за горизонтом;
- окно тренера, которое цикл лишь переиспользовал, остаётся ``available``;
- удаление клиента из списка закрывает его правила — цикл больше не ставит ему записи;
- клиенту ставится ровно одно сообщение на снятое правило (sandbox / без Telegram — ни одного);
- снятие — одна транзакция: сбой посередине оставляет всё как было;
- отмена ОДНОЙ автозаписи (тренер / клиент / перенос) мягко скрывает окно цикла
  (``status='cancelled'``): запись, уведомления, история и статистика остаются.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import (
    cancel_booking,
    cancel_booking_by_client,
    detach_trainer_client_from_roster_miniapp,
    list_booking_history_for_client,
)
from src.application.recurring_use_cases import (
    cancel_recurring_client_slot,
    create_recurring_client_slot,
    list_pending_recurring_removed_notices,
    maintain_recurring_horizon,
    materialize_recurring_horizon,
    prune_recurring_bookings_beyond_horizon,
    this_week_monday,
)
from src.application.stats_use_cases import get_trainer_stats_dashboard
from src.application.recurring_use_cases import find_available_slot_in_week
from src.application.trainer_schedule_use_cases import (
    ensure_individual_slot_for_quick_book,
    list_slots,
    replace_slots_for_day,
)
from src.bot.trainer_cancel_client_notify import process_recurring_removed_notices_batch
from tests.conftest import belarus_test_phone, unique_test_telegram_id
from tests.db_catalog_helpers import require_seed_service_id

DOW = 1  # Tuesday
ST = time(10, 0)
ET = time(11, 0)


async def _seed_trainer(session: AsyncSession) -> int:
    service_id = await require_seed_service_id(session)
    r = await session.execute(
        text("INSERT INTO trainers (status, telegram_id) VALUES ('active', :tg) RETURNING id"),
        {"tg": unique_test_telegram_id()},
    )
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


# --- One-off cancel of a single auto-booking: soft-hide, never DELETE -------------------------


async def _week1_booking(session: AsyncSession, trainer_id: int, client_id: int) -> tuple[int, int]:
    r = await session.execute(
        text(
            """
            SELECT b.id, s.id FROM bookings b JOIN slots s ON s.id = b.slot_id
            WHERE b.trainer_id = :tid AND b.client_id = :cid AND s.slot_date = :d
              AND b.status IN ('pending', 'confirmed')
            """
        ),
        {"tid": trainer_id, "cid": client_id, "d": _week_date(1)},
    )
    row = r.fetchone()
    return int(row[0]), int(row[1])


async def _slot_status(session: AsyncSession, slot_id: int) -> str | None:
    r = await session.execute(text("SELECT status FROM slots WHERE id = :id"), {"id": slot_id})
    v = r.scalar()
    return str(v) if v is not None else None


async def _booking_row(session: AsyncSession, booking_id: int) -> tuple[str, str | None, int]:
    r = await session.execute(
        text("SELECT status, cancellation_source, slot_id FROM bookings WHERE id = :id"),
        {"id": booking_id},
    )
    row = r.fetchone()
    return str(row[0]), row[1], int(row[2])


async def _client_tg(session: AsyncSession, client_id: int) -> int:
    r = await session.execute(text("SELECT telegram_id FROM clients WHERE id = :id"), {"id": client_id})
    return int(r.scalar_one())


async def _cancellations_month(session: AsyncSession, trainer_id: int) -> int:
    return int((await get_trainer_stats_dashboard(session, trainer_id))["cancellations_month"])


async def _assert_hidden_but_kept(
    session: AsyncSession, trainer_id: int, client_id: int, booking_id: int, slot_id: int, source: str
) -> None:
    # The window is gone from every slot listing...
    assert await _slot_status(session, slot_id) == "cancelled"
    listed = await list_slots(session, trainer_id, _week_date(1), _week_date(1))
    assert slot_id not in {int(s["id"]) for s in listed}
    assert await find_available_slot_in_week(
        session, trainer_id, this_week_monday() + timedelta(days=7), DOW, ST
    ) is None
    # ...but the booking itself survives: status, source, slot link, client history.
    status, src, sid = await _booking_row(session, booking_id)
    assert (status, src, sid) == ("cancelled", source, slot_id)
    history, _ = await list_booking_history_for_client(
        session, await _client_tg(session, client_id), acting_client_id=client_id
    )
    assert booking_id in {int(h["id"]) for h in history}
    # The cycle does not refill the skipped week, nothing revives the slot.
    assert await materialize_recurring_horizon(
        session, trainer_id, horizon_weeks=3, min_week_index=1
    ) == 0
    assert await _slot_status(session, slot_id) == "cancelled"


@pytest.mark.asyncio
async def test_trainer_cancels_one_auto_booking_hides_cycle_window(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, sid = await _week1_booking(db_session, trainer_id, client_id)
    before = await _cancellations_month(db_session, trainer_id)

    assert await cancel_booking(db_session, bid, trainer_id) is True

    await _assert_hidden_but_kept(db_session, trainer_id, client_id, bid, sid, "trainer")
    r = await db_session.execute(
        text("SELECT COUNT(*) FROM booking_cancel_notifications WHERE booking_id = :b AND sent_at IS NULL"),
        {"b": bid},
    )
    assert int(r.scalar_one()) == 1
    in_month = _week_date(1).month == date.today().month and _week_date(1).year == date.today().year
    assert await _cancellations_month(db_session, trainer_id) == before + (1 if in_month else 0)


@pytest.mark.asyncio
async def test_client_cancels_one_auto_booking_hides_cycle_window(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, sid = await _week1_booking(db_session, trainer_id, client_id)

    payload = await cancel_booking_by_client(
        db_session, bid, await _client_tg(db_session, client_id), acting_client_id=client_id
    )
    assert payload is not None and payload["already_cancelled"] is False

    await _assert_hidden_but_kept(db_session, trainer_id, client_id, bid, sid, "client")
    r = await db_session.execute(
        text(
            "SELECT kind, recipient_role FROM booking_party_notifications "
            "WHERE booking_id = :b AND sent_at IS NULL ORDER BY kind"
        ),
        {"b": bid},
    )
    assert [tuple(row) for row in r.fetchall()] == [
        ("client_cancel_confirm", "client"),
        ("client_cancel_trainer", "trainer"),
    ]


@pytest.mark.asyncio
async def test_one_off_cancel_keeps_reused_trainer_window_available(db_session: AsyncSession) -> None:
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
    await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, sid = await _week1_booking(db_session, trainer_id, client_id)
    assert sid == template_slot_id

    assert await cancel_booking(db_session, bid, trainer_id) is True
    assert await _slot_status(db_session, template_slot_id) == "available"
    listed = await list_slots(db_session, trainer_id, _week_date(1), _week_date(1))
    assert template_slot_id in {int(s["id"]) for s in listed}


@pytest.mark.asyncio
async def test_trainer_can_open_window_again_over_hidden_one(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, hidden_id = await _week1_booking(db_session, trainer_id, client_id)
    assert await cancel_booking(db_session, bid, trainer_id) is True
    assert await _slot_status(db_session, hidden_id) == "cancelled"

    # Day editor («сохранить день») with the same start: a fresh window, not «already exists».
    await replace_slots_for_day(
        db_session,
        trainer_id,
        _week_date(1),
        {ST.hour * 60 + ST.minute},
        per_slot_duration={ST.hour * 60 + ST.minute: 60},
    )
    listed = [
        s for s in await list_slots(db_session, trainer_id, _week_date(1), _week_date(1))
        if s["start_time"] == ST
    ]
    assert len(listed) == 1
    new_id = int(listed[0]["id"])
    assert new_id != hidden_id
    assert listed[0]["status"] == "available"
    # Quick book reuses that new window (the hidden one does not block or get picked).
    sid = await ensure_individual_slot_for_quick_book(
        db_session, trainer_id, _week_date(1), ST.hour * 60 + ST.minute, 60,
        allow_off_grid_interval=True,
    )
    assert sid == new_id
    assert await _slot_status(db_session, hidden_id) == "cancelled"


@pytest.mark.asyncio
async def test_quick_book_over_hidden_window_inserts_new_slot(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, hidden_id = await _week1_booking(db_session, trainer_id, client_id)
    assert await cancel_booking(db_session, bid, trainer_id) is True

    sid = await ensure_individual_slot_for_quick_book(
        db_session, trainer_id, _week_date(1), ST.hour * 60 + ST.minute, 60,
        allow_off_grid_interval=True,
    )
    assert sid != hidden_id
    r = await db_session.execute(
        text("SELECT created_for_recurring_client_slot_id FROM slots WHERE id = :id"), {"id": sid}
    )
    assert r.scalar() is None  # the trainer's own window, not a cycle one


@pytest.mark.asyncio
async def test_rule_removal_after_one_off_cancel_leaves_hidden_slot_alone(db_session: AsyncSession) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client(db_session, trainer_id)
    rid = await _rule_with_three_weeks(db_session, trainer_id, client_id)
    bid, hidden_id = await _week1_booking(db_session, trainer_id, client_id)
    assert await cancel_booking(db_session, bid, trainer_id) is True

    ok, removed = await cancel_recurring_client_slot(db_session, trainer_id, rid)
    assert ok is True
    assert removed == 2  # weeks 2 and 3; week 1 was already cancelled
    assert await _slot_status(db_session, hidden_id) == "cancelled"
    assert await _booking_row(db_session, bid) == ("cancelled", "trainer", hidden_id)
    slots = await _slots_on_rule_dates(db_session, trainer_id)
    assert slots == {_week_date(1): (hidden_id, "cancelled")}
