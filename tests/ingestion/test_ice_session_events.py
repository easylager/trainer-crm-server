"""Журнал слотов: триггер на ice_sessions пишет added/removed/changed и источник."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.ingestion.ttl import purge_ice_scrape_ttl


async def _arena(db_session) -> int:
    city = (
        await db_session.execute(
            text(
                "INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                "VALUES ('EventsCity', 'BY', 'BY_BASE', true, 9400) RETURNING id"
            )
        )
    ).scalar_one()
    return int(
        (
            await db_session.execute(
                text(
                    "INSERT INTO arenas (city_id, name, address, is_active, is_confirmed) "
                    "VALUES (:c, 'Каток Журнал', 'ул. 1', true, true) RETURNING id"
                ),
                {"c": city},
            )
        ).scalar_one()
    )


async def _slot(db_session, arena_id: int, *, hours_ahead: float = 48, source_id: str | None = "run:1:10:00",
                basis: str = "live", status: str = "active") -> int:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_ahead)
    return int(
        (
            await db_session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local, currency_code, status, source_id, schedule_basis)
                    VALUES (:a, 'public_skate', :s, :e, (:s AT TIME ZONE 'Europe/Minsk')::date,
                        (:s AT TIME ZONE 'Europe/Minsk')::time, (:e AT TIME ZONE 'Europe/Minsk')::time,
                        'BYN', :st, :src, :basis)
                    RETURNING id
                    """
                ),
                {"a": arena_id, "s": start, "e": start + timedelta(hours=1), "st": status,
                 "src": source_id, "basis": basis},
            )
        ).scalar_one()
    )


async def _events(db_session, arena_id: int) -> list[tuple[str, str]]:
    rows = await db_session.execute(
        text("SELECT event, source FROM ice_session_events WHERE arena_id = :a ORDER BY id"), {"a": arena_id}
    )
    return [(r[0], r[1]) for r in rows]


@pytest.mark.asyncio
async def test_insert_update_delete_are_logged(db_session) -> None:
    arena_id = await _arena(db_session)
    sid = await _slot(db_session, arena_id)
    assert await _events(db_session, arena_id) == [("added", "parser")]

    # цена и observed_at — не событие
    await db_session.execute(text("UPDATE ice_sessions SET price_adult_minor = 500, observed_at = now() WHERE id = :i"), {"i": sid})
    assert await _events(db_session, arena_id) == [("added", "parser")]

    await db_session.execute(
        text("UPDATE ice_sessions SET ends_at_utc = ends_at_utc + interval '30 minutes' WHERE id = :i"), {"i": sid}
    )
    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :i"), {"i": sid})
    assert await _events(db_session, arena_id) == [("added", "parser"), ("changed", "parser"), ("removed", "parser")]


@pytest.mark.asyncio
async def test_past_slots_and_expiry_are_not_logged(db_session) -> None:
    arena_id = await _arena(db_session)
    await _slot(db_session, arena_id, hours_ahead=-48)  # уже закончился
    future = await _slot(db_session, arena_id)
    await db_session.execute(text("DELETE FROM ice_session_events WHERE arena_id = :a"), {"a": arena_id})
    # слот прошёл, потом его экспирят/удаляют — шума нет
    await db_session.execute(
        text("UPDATE ice_sessions SET starts_at_utc = now() - interval '3 hours', ends_at_utc = now() - interval '2 hours' WHERE id = :i"),
        {"i": future},
    )
    await db_session.execute(text("UPDATE ice_sessions SET status = 'expired' WHERE id = :i"), {"i": future})
    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :i"), {"i": future})
    assert await _events(db_session, arena_id) == []


@pytest.mark.asyncio
async def test_cancel_counts_as_removed_and_restore_as_added(db_session) -> None:
    arena_id = await _arena(db_session)
    sid = await _slot(db_session, arena_id)
    await db_session.execute(text("UPDATE ice_sessions SET status = 'cancelled' WHERE id = :i"), {"i": sid})
    await db_session.execute(text("UPDATE ice_sessions SET status = 'active' WHERE id = :i"), {"i": sid})
    assert [e for e, _ in await _events(db_session, arena_id)] == ["added", "removed", "added"]


@pytest.mark.asyncio
async def test_source_is_taken_from_row_and_overridden_by_tag(db_session) -> None:
    arena_id = await _arena(db_session)
    await _slot(db_session, arena_id, source_id="admin", basis="manual", hours_ahead=10)
    await _slot(db_session, arena_id, source_id="run:7:x", basis="photo", hours_ahead=11)
    await _slot(db_session, arena_id, source_id="run:8:x", hours_ahead=12)
    await _slot(db_session, arena_id, source_id="little:abc", hours_ahead=13)
    await _slot(db_session, arena_id, source_id=None, hours_ahead=14)
    assert [s for _, s in await _events(db_session, arena_id)] == [
        "manual", "screenshot", "parser", "script", "script",
    ]

    sid = await _slot(db_session, arena_id, hours_ahead=60)  # parser-строка
    await db_session.execute(text("SELECT set_config('app.change_source', 'manual', true)"))
    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :i"), {"i": sid})
    assert (await _events(db_session, arena_id))[-1] == ("removed", "manual")


@pytest.mark.asyncio
async def test_admin_delete_use_case_tags_manual(db_session) -> None:
    from src.application.ice_session_use_cases import delete_ice_session

    arena_id = await _arena(db_session)
    sid = await _slot(db_session, arena_id)  # строка парсера
    await delete_ice_session(db_session, sid)
    assert (await _events(db_session, arena_id))[-1] == ("removed", "manual")


@pytest.mark.asyncio
async def test_ttl_purges_events_older_than_30_days(db_session) -> None:
    arena_id = await _arena(db_session)
    await _slot(db_session, arena_id)
    await db_session.execute(
        text("UPDATE ice_session_events SET occurred_at = now() - interval '31 days' WHERE arena_id = :a"),
        {"a": arena_id},
    )
    await _slot(db_session, arena_id, hours_ahead=72)
    stats = await purge_ice_scrape_ttl(db_session, now=datetime.now(timezone.utc))
    assert stats.events_deleted >= 1
    assert len(await _events(db_session, arena_id)) == 1
