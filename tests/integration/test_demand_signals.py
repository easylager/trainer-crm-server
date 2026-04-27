"""
Integration tests for demand signals (Lead Mode foundation): record + window aggregation
+ dedup against a real Postgres test DB. Requires `alembic upgrade head` against trainer_crm_test.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.demand_signals_use_cases import (
    RECAP_WINDOW_7D,
    RECAP_WINDOW_14D,
    SignalsRecap,
    get_signals_lifetime_totals,
    get_signals_recap,
    get_signals_since,
    record_booking_attempt_blocked,
    record_contact_click,
    record_profile_view,
)
from src.infrastructure.db.models import (
    DEMAND_EVENT_BOOKING_ATTEMPT_BLOCKED,
    DEMAND_EVENT_CONTACT_CLICK,
    DEMAND_EVENT_PROFILE_VIEW,
    DEMAND_SOURCE_CATALOG,
    DEMAND_SOURCE_CLIENT_APP,
)


async def _create_trainer(session: AsyncSession) -> int:
    """Bare-minimum trainer row — demand events need only the id."""
    r = await session.execute(text("INSERT INTO trainers (status) VALUES ('active') RETURNING id"))
    (trainer_id,) = r.fetchone()
    await session.commit()
    return trainer_id


async def _count_events(session: AsyncSession, trainer_id: int) -> int:
    r = await session.execute(
        text("SELECT COUNT(*) FROM trainer_demand_events WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    return int(r.scalar() or 0)


@pytest.mark.asyncio
async def test_record_profile_view_inserts_row(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    inserted = await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    assert inserted is True
    assert await _count_events(db_session, trainer_id) == 1


@pytest.mark.asyncio
async def test_profile_view_dedup_collapses_same_day_refresh(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    args = dict(
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    first = await record_profile_view(db_session, **args)
    second = await record_profile_view(db_session, **args)
    third = await record_profile_view(db_session, **args)
    assert first is True
    assert second is False
    assert third is False
    assert await _count_events(db_session, trainer_id) == 1


@pytest.mark.asyncio
async def test_profile_view_distinct_visitors_count_separately(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="5.6.7.8",
        user_agent="Mozilla/5.0",
    )
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.2.3.4",
        user_agent="Chrome/100",
    )
    assert await _count_events(db_session, trainer_id) == 3


@pytest.mark.asyncio
async def test_view_without_fingerprint_is_never_deduped(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip=None,
        user_agent=None,
    )
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip=None,
        user_agent=None,
    )
    assert await _count_events(db_session, trainer_id) == 2


@pytest.mark.asyncio
async def test_booking_attempt_blocked_never_deduped(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    for _ in range(3):
        await record_booking_attempt_blocked(
            db_session,
            trainer_id=trainer_id,
            source=DEMAND_SOURCE_CLIENT_APP,
        )
    assert await _count_events(db_session, trainer_id) == 3


@pytest.mark.asyncio
async def test_contact_click_dedup_same_day(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    args = dict(
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    a = await record_contact_click(db_session, **args)
    b = await record_contact_click(db_session, **args)
    assert (a, b) == (True, False)
    assert await _count_events(db_session, trainer_id) == 1


@pytest.mark.asyncio
async def test_get_signals_recap_zero_filled_when_empty(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    recap = await get_signals_recap(db_session, trainer_id=trainer_id, window_days=RECAP_WINDOW_14D)
    assert isinstance(recap, SignalsRecap)
    assert recap.profile_views == 0
    assert recap.contact_clicks == 0
    assert recap.booking_attempts_blocked == 0
    assert recap.has_any_demand is False
    assert recap.window_days == RECAP_WINDOW_14D


@pytest.mark.asyncio
async def test_get_signals_recap_aggregates_mixed_kinds(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    # 2 unique views + 1 click + 3 blocked attempts (blocked never deduped).
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.1.1.1",
        user_agent="A",
    )
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="2.2.2.2",
        user_agent="A",
    )
    await record_contact_click(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="3.3.3.3",
        user_agent="A",
    )
    for _ in range(3):
        await record_booking_attempt_blocked(
            db_session, trainer_id=trainer_id, source=DEMAND_SOURCE_CLIENT_APP
        )

    recap = await get_signals_recap(db_session, trainer_id=trainer_id, window_days=RECAP_WINDOW_14D)
    assert recap.profile_views == 2
    assert recap.contact_clicks == 1
    assert recap.booking_attempts_blocked == 3
    assert recap.has_any_demand is True


@pytest.mark.asyncio
async def test_recap_excludes_events_outside_window(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    # Two events: one inside window (today), one outside (60 days ago).
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="1.1.1.1",
        user_agent="A",
    )
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_demand_events (trainer_id, kind, source, occurred_at)
            VALUES (:tid, :kind, :src, :ts)
            """
        ),
        {
            "tid": trainer_id,
            "kind": DEMAND_EVENT_PROFILE_VIEW,
            "src": DEMAND_SOURCE_CATALOG,
            "ts": datetime.now(timezone.utc) - timedelta(days=60),
        },
    )
    await db_session.commit()

    recap_7 = await get_signals_recap(db_session, trainer_id=trainer_id, window_days=RECAP_WINDOW_7D)
    assert recap_7.profile_views == 1


@pytest.mark.asyncio
async def test_get_signals_since_custom_anchor(db_session: AsyncSession) -> None:
    """Recovery nudges call this with since=lead_mode_entered_at."""
    trainer_id = await _create_trainer(db_session)
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    # Event before cutoff — must be excluded.
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_demand_events (trainer_id, kind, source, occurred_at)
            VALUES (:tid, :kind, :src, :ts)
            """
        ),
        {
            "tid": trainer_id,
            "kind": DEMAND_EVENT_PROFILE_VIEW,
            "src": DEMAND_SOURCE_CATALOG,
            "ts": cutoff - timedelta(hours=1),
        },
    )
    await db_session.commit()
    # Event after cutoff — must be included.
    await record_profile_view(
        db_session,
        trainer_id=trainer_id,
        source=DEMAND_SOURCE_CATALOG,
        client_ip="9.9.9.9",
        user_agent="A",
    )

    recap = await get_signals_since(db_session, trainer_id=trainer_id, since=cutoff)
    assert recap.profile_views == 1


@pytest.mark.asyncio
async def test_unknown_source_rejected(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    with pytest.raises(ValueError):
        await record_profile_view(
            db_session,
            trainer_id=trainer_id,
            source="bogus_source",
            client_ip="1.2.3.4",
            user_agent="A",
        )


@pytest.mark.asyncio
async def test_unsupported_window_rejected(db_session: AsyncSession) -> None:
    trainer_id = await _create_trainer(db_session)
    with pytest.raises(ValueError):
        await get_signals_recap(db_session, trainer_id=trainer_id, window_days=42)


@pytest.mark.asyncio
async def test_recap_isolated_per_trainer(db_session: AsyncSession) -> None:
    """One trainer's events must not leak into another's recap."""
    a = await _create_trainer(db_session)
    b = await _create_trainer(db_session)
    await record_profile_view(
        db_session, trainer_id=a, source=DEMAND_SOURCE_CATALOG, client_ip="1.1.1.1", user_agent="A"
    )
    await record_contact_click(
        db_session, trainer_id=b, source=DEMAND_SOURCE_CATALOG, client_ip="1.1.1.1", user_agent="A"
    )

    recap_a = await get_signals_recap(db_session, trainer_id=a)
    recap_b = await get_signals_recap(db_session, trainer_id=b)

    assert recap_a.profile_views == 1
    assert recap_a.contact_clicks == 0
    assert recap_b.profile_views == 0
    assert recap_b.contact_clicks == 1


@pytest.mark.asyncio
async def test_lifetime_totals_sum_all_rows(db_session: AsyncSession) -> None:
    """Aggregate since epoch = all events for trainer (used by stats «каталог» block)."""
    tid = await _create_trainer(db_session)
    await record_profile_view(
        db_session, trainer_id=tid, source=DEMAND_SOURCE_CATALOG, client_ip="9.9.1.1", user_agent="A"
    )
    await record_profile_view(
        db_session, trainer_id=tid, source=DEMAND_SOURCE_CATALOG, client_ip="9.9.1.2", user_agent="B"
    )
    await record_contact_click(
        db_session, trainer_id=tid, source=DEMAND_SOURCE_CATALOG, client_ip="1.1.1.1", user_agent="C"
    )
    tot = await get_signals_lifetime_totals(db_session, trainer_id=tid)
    assert tot["profile_views"] == 2
    assert tot["contact_clicks"] == 1
