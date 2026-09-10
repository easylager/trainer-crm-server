"""
Integration tests for the G-P5 metrics (TASK-096): «вторая запись за 7 дней» and share counts.
Real Postgres — the metric is one SQL statement, so mocking it would test nothing.
Requires `alembic upgrade head` against trainer_crm_test.

The metric is global by design (it describes the product, not a subset), and the test DB carries
rows from other suites. So every assertion here is a **delta** around the fixtures this test
inserts — that is also exactly how the baseline is read in production.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_delight_metrics import (
    get_second_booking_within_7d,
    get_share_counts,
    record_client_share,
    share_actor_hash,
)
from src.infrastructure.db.models import (
    CLIENT_SHARE_KIND_ICE_CITY_DAY,
    CLIENT_SHARE_KIND_TRAINER,
)
from tests.conftest import unique_test_telegram_id

AS_OF = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
# Inside the 90-day cohort window and at least 8 days before AS_OF, so a fixture client
# has had a full 7 days to come back.
FIRST_AT = AS_OF - timedelta(days=40)


async def _fixture_ids(session: AsyncSession) -> dict:
    """Minimum rows the bookings FKs demand: trainer + service."""
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    # `services` is a global catalogue (no trainer_id) — reuse a row when one already exists.
    r = await session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    row = r.fetchone()
    if row is None:
        r = await session.execute(text("INSERT INTO services (name) VALUES ('Лёд') RETURNING id"))
        row = r.fetchone()
    (service_id,) = row
    await session.commit()
    return {"trainer_id": trainer_id, "service_id": service_id}


async def _make_client(session: AsyncSession, telegram_id: int) -> int:
    r = await session.execute(
        text("INSERT INTO clients (telegram_id, first_name) VALUES (:tg, 'Тест') RETURNING id"),
        {"tg": telegram_id},
    )
    (client_id,) = r.fetchone()
    await session.commit()
    return client_id


async def _make_slot(session: AsyncSession, trainer_id: int, starts_at: datetime) -> int:
    r = await session.execute(
        text(
            "INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status) "
            "VALUES (:tid, :d, :st, :et, 'booked') RETURNING id"
        ),
        {
            "tid": trainer_id,
            "d": starts_at.date(),
            "st": starts_at.time(),
            "et": (starts_at + timedelta(hours=1)).time(),
        },
    )
    (slot_id,) = r.fetchone()
    await session.commit()
    return slot_id


async def _book(
    session: AsyncSession,
    ids: dict,
    client_id: int,
    created_at: datetime,
    *,
    status: str = "confirmed",
    is_sandbox: bool = False,
) -> None:
    slot_id = await _make_slot(session, ids["trainer_id"], created_at + timedelta(days=1))
    await session.execute(
        text(
            """
            INSERT INTO bookings
                (slot_id, trainer_id, client_id, service_id, created_at, status, is_sandbox)
            VALUES (:slot, :tid, :cid, :sid, :created, :status, :sandbox)
            """
        ),
        {
            "slot": slot_id,
            "tid": ids["trainer_id"],
            "cid": client_id,
            "sid": ids["service_id"],
            "created": created_at,
            "status": status,
            "sandbox": is_sandbox,
        },
    )
    await session.commit()


async def _metric(session: AsyncSession) -> dict:
    return await get_second_booking_within_7d(session, as_of=AS_OF)


def _delta(after: dict, before: dict, key: str) -> int:
    return int(after[key]) - int(before[key])


@pytest.mark.asyncio
async def test_second_booking_within_window_counts_as_returned(
    db_session: AsyncSession,
) -> None:
    ids = await _fixture_ids(db_session)
    before = await _metric(db_session)

    returner = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, returner, FIRST_AT)
    await _book(db_session, ids, returner, FIRST_AT + timedelta(days=6))

    lonely = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, lonely, FIRST_AT)

    after = await _metric(db_session)
    assert _delta(after, before, "cohort_size") == 2
    assert _delta(after, before, "returned") == 1


@pytest.mark.asyncio
async def test_second_booking_on_day_eight_does_not_count(
    db_session: AsyncSession,
) -> None:
    ids = await _fixture_ids(db_session)
    before = await _metric(db_session)

    late = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, late, FIRST_AT)
    await _book(db_session, ids, late, FIRST_AT + timedelta(days=8))

    after = await _metric(db_session)
    assert _delta(after, before, "cohort_size") == 1
    assert _delta(after, before, "returned") == 0


@pytest.mark.asyncio
async def test_cancelled_second_booking_is_not_a_return(
    db_session: AsyncSession,
) -> None:
    """A cancelled booking is not a visit. Counting it would flatter the gate."""
    ids = await _fixture_ids(db_session)
    before = await _metric(db_session)

    client_id = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, client_id, FIRST_AT)
    await _book(db_session, ids, client_id, FIRST_AT + timedelta(days=3), status="cancelled")

    after = await _metric(db_session)
    assert _delta(after, before, "cohort_size") == 1
    assert _delta(after, before, "returned") == 0


@pytest.mark.asyncio
async def test_client_still_inside_window_is_pending_not_failed(
    db_session: AsyncSession,
) -> None:
    """First booking two days ago: seven days haven't passed, so neither success nor failure."""
    ids = await _fixture_ids(db_session)
    before = await _metric(db_session)

    fresh = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, fresh, AS_OF - timedelta(days=2))

    after = await _metric(db_session)
    assert _delta(after, before, "cohort_size") == 0
    assert _delta(after, before, "pending_cohort") == 1


@pytest.mark.asyncio
async def test_sandbox_bookings_are_excluded(
    db_session: AsyncSession,
) -> None:
    ids = await _fixture_ids(db_session)
    before = await _metric(db_session)

    demo = await _make_client(db_session, unique_test_telegram_id())
    await _book(db_session, ids, demo, FIRST_AT, is_sandbox=True)
    await _book(db_session, ids, demo, FIRST_AT + timedelta(days=2), is_sandbox=True)

    after = await _metric(db_session)
    assert _delta(after, before, "cohort_size") == 0
    assert _delta(after, before, "returned") == 0


@pytest.mark.asyncio
async def test_empty_cohort_reads_as_unknown_not_zero(db_session: AsyncSession) -> None:
    """
    A window before the product existed has no cohort. «Не знаем» and «никто не вернулся»
    are different facts; a gate that confuses them is worse than no gate.
    """
    result = await get_second_booking_within_7d(
        db_session, as_of=datetime(2019, 1, 1, tzinfo=timezone.utc), cohort_days=30
    )
    assert result["cohort_size"] == 0
    assert result["rate_pct"] is None


@pytest.mark.asyncio
async def test_rate_pct_is_returned_over_cohort(
    db_session: AsyncSession,
) -> None:
    ids = await _fixture_ids(db_session)
    result = await _metric(db_session)
    if result["cohort_size"]:
        assert result["rate_pct"] == round(
            100.0 * result["returned"] / result["cohort_size"], 1
        )
    else:  # pragma: no cover — only on a bookings-free database
        assert result["rate_pct"] is None
    assert ids["trainer_id"] > 0


@pytest.mark.asyncio
async def test_cohort_shorter_than_return_window_is_rejected(db_session: AsyncSession) -> None:
    """A 5-day cohort cannot answer a 7-day question. Fail loudly, don't return a lie."""
    with pytest.raises(ValueError):
        await get_second_booking_within_7d(db_session, as_of=AS_OF, cohort_days=5)


@pytest.mark.asyncio
async def test_record_client_share_and_count(db_session: AsyncSession) -> None:
    before = await get_share_counts(db_session, days=30)

    await record_client_share(
        db_session,
        kind=CLIENT_SHARE_KIND_ICE_CITY_DAY,
        share_context="ice_tab",
        telegram_id=777001,
    )
    await record_client_share(
        db_session,
        kind=CLIENT_SHARE_KIND_ICE_CITY_DAY,
        share_context="ice_tab",
        telegram_id=777001,
    )
    await record_client_share(
        db_session,
        kind=CLIENT_SHARE_KIND_TRAINER,
        share_context="catalog",
        telegram_id=777002,
    )

    after = await get_share_counts(db_session, days=30)
    ice_before = before["by_kind"].get(CLIENT_SHARE_KIND_ICE_CITY_DAY, {"events": 0, "sharers": 0})
    ice_after = after["by_kind"][CLIENT_SHARE_KIND_ICE_CITY_DAY]
    assert ice_after["events"] - ice_before["events"] == 2
    # Same person twice in a day is two shares but one sharer.
    assert ice_after["sharers"] - ice_before["sharers"] == 1
    assert after["events_total"] - before["events_total"] == 3


@pytest.mark.asyncio
async def test_unknown_share_kind_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await record_client_share(db_session, kind="whatever_marketing_wants")


def test_actor_hash_is_stable_and_anonymous_safe() -> None:
    day = AS_OF.date()
    a = share_actor_hash(555, CLIENT_SHARE_KIND_TRAINER, day)
    b = share_actor_hash(555, CLIENT_SHARE_KIND_TRAINER, day)
    assert a == b and a is not None and "555" not in a
    assert share_actor_hash(None, CLIENT_SHARE_KIND_TRAINER, day) is None
