"""TASK-329 AC1/AC2/AC5/AC6: запись волн, админское сохранение, поля карточки."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from src.api.app import app
from src.application.arena_profile import backfill_arena_profiles
from src.application.arena_public_use_cases import get_public_arena_card
from src.application.schedule_waves import (
    arena_schedule_horizon,
    parser_wave_recorder,
    record_admin_wave_after_commit,
    record_schedule_wave,
    schedule_card_fields,
)
from tests.api.test_admin_ice_sessions import patch_admin_principal

MINSK = ZoneInfo("Europe/Minsk")


async def _arena(db_session) -> int:
    cid = (
        await db_session.execute(text("SELECT id FROM cities WHERE country = 'BY' ORDER BY id LIMIT 1"))
    ).scalar()
    if cid is None:
        cid = (
            await db_session.execute(
                text(
                    """
                    INSERT INTO cities (name, country, price_group, is_active)
                    VALUES (:n, 'BY', 'BY_BASE', true) RETURNING id
                    """
                ),
                {"n": f"WaveCity-{uuid.uuid4().hex[:6]}"},
            )
        ).scalar_one()
    arena_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO arenas (city_id, name, address, is_active, is_confirmed)
                VALUES (:cid, :name, 'ул. Волновая, 1', true, true) RETURNING id
                """
            ),
            {"cid": int(cid), "name": f"Волна {uuid.uuid4().hex[:8]}"},
        )
    ).scalar_one()
    await backfill_arena_profiles(db_session)
    await db_session.flush()
    return int(arena_id)


async def _ice(db_session, arena_id: int, day: date, *, kind="public_skate", status="active", hour=12) -> int:
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=MINSK)
    return (
        await db_session.execute(
            text(
                """
                INSERT INTO ice_sessions (
                    arena_id, kind, starts_at_utc, ends_at_utc, local_date, starts_at_local,
                    ends_at_local, currency_code, status, source_id
                ) VALUES (
                    :aid, :kind, :s, :e, :d, :sl, :el, 'BYN', :status, :src
                ) RETURNING id
                """
            ),
            {
                "aid": arena_id,
                "kind": kind,
                "s": start.astimezone(timezone.utc),
                "e": (start + timedelta(minutes=60)).astimezone(timezone.utc),
                "d": day,
                "sl": start.time(),
                "el": (start + timedelta(minutes=60)).time(),
                "status": status,
                "src": f"run:test:{uuid.uuid4().hex[:6]}",
            },
        )
    ).scalar_one()


async def _rows(db_session, arena_id: int) -> list[tuple]:
    result = await db_session.execute(
        text(
            """
            SELECT source, horizon_before, horizon_after
            FROM ice_schedule_waves WHERE arena_id = :a ORDER BY detected_at, id
            """
        ),
        {"a": arena_id},
    )
    return [tuple(r) for r in result.fetchall()]


NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
D = date(2026, 10, 25)


@pytest.mark.asyncio
async def test_first_record_is_seed_then_growth_is_wave(db_session) -> None:
    arena_id = await _arena(db_session)
    await _ice(db_session, arena_id, D)
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW) == "seed"
    # горизонт не вырос — ничего
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW + timedelta(hours=1)) is None
    await _ice(db_session, arena_id, D + timedelta(days=7))
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW + timedelta(hours=2)) == "wave"
    assert await _rows(db_session, arena_id) == [
        ("seed", None, D),
        ("parser", D, D + timedelta(days=7)),
    ]


@pytest.mark.asyncio
async def test_seed_with_empty_card_then_first_sessions_is_wave(db_session) -> None:
    arena_id = await _arena(db_session)
    assert await record_schedule_wave(db_session, arena_id, source="admin", now=NOW) == "seed"
    await _ice(db_session, arena_id, D)
    assert await record_schedule_wave(db_session, arena_id, source="admin", now=NOW) == "wave"
    assert await _rows(db_session, arena_id) == [("seed", None, None), ("admin", None, D)]


@pytest.mark.asyncio
async def test_shrink_and_regrow_to_same_horizon_is_not_a_wave(db_session) -> None:
    arena_id = await _arena(db_session)
    await _ice(db_session, arena_id, D)
    far = await _ice(db_session, arena_id, D + timedelta(days=3))
    await record_schedule_wave(db_session, arena_id, source="parser", now=NOW)
    await db_session.execute(text("DELETE FROM ice_sessions WHERE id = :id"), {"id": far})
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW) is None
    await _ice(db_session, arena_id, D + timedelta(days=3))
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW) is None
    # все сеансы прошли — горизонт пуст, тоже не волна
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW + timedelta(days=30)) is None
    assert [r[0] for r in await _rows(db_session, arena_id)] == ["seed"]


@pytest.mark.asyncio
async def test_backfill_rows_are_not_a_baseline(db_session) -> None:
    arena_id = await _arena(db_session)
    await db_session.execute(
        text("INSERT INTO ice_schedule_waves (arena_id, detected_at, source) VALUES (:a, :t, 'backfill')"),
        {"a": arena_id, "t": NOW - timedelta(days=3)},
    )
    await _ice(db_session, arena_id, D)
    # без seed первая живая запись — seed, а не «волна» от backfill(NULL) → D
    assert await record_schedule_wave(db_session, arena_id, source="parser", now=NOW) == "seed"


@pytest.mark.asyncio
async def test_horizon_counts_only_future_active_public_kinds(db_session) -> None:
    arena_id = await _arena(db_session)
    await _ice(db_session, arena_id, D)
    await _ice(db_session, arena_id, D + timedelta(days=5), status="cancelled")
    await _ice(db_session, arena_id, D + timedelta(days=6), kind="hockey_practice")
    await _ice(db_session, arena_id, D + timedelta(days=1), kind="open_ice")
    await _ice(db_session, arena_id, date(2026, 10, 20))  # прошёл
    assert await arena_schedule_horizon(db_session, arena_id, now=NOW) == D + timedelta(days=1)
    assert await arena_schedule_horizon(db_session, arena_id, now=NOW + timedelta(days=10)) is None


@pytest.mark.asyncio
async def test_live_sources_only(db_session) -> None:
    arena_id = await _arena(db_session)
    with pytest.raises(ValueError):
        await record_schedule_wave(db_session, arena_id, source="backfill", now=NOW)


@pytest.mark.asyncio
async def test_parser_recorder_uses_own_session_and_commits(db_session) -> None:
    arena_id = await _arena(db_session)
    await _ice(db_session, arena_id, date.today() + timedelta(days=2))

    @asynccontextmanager
    async def factory():
        yield db_session

    assert await parser_wave_recorder(factory)(arena_id) == "seed"
    assert [r[0] for r in await _rows(db_session, arena_id)] == ["seed"]


@pytest.mark.asyncio
async def test_parser_recorder_swallows_failure(caplog) -> None:
    def broken_factory():
        raise RuntimeError("no database")

    assert await parser_wave_recorder(broken_factory)(1) is None
    assert "schedule wave record failed" in caplog.text


@pytest.mark.asyncio
async def test_admin_recorder_failure_is_swallowed(db_session, monkeypatch, caplog) -> None:
    import src.application.schedule_waves as mod

    async def boom(*args, **kwargs):
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(mod, "record_schedule_wave", boom)
    assert await record_admin_wave_after_commit(db_session, 1) is None
    assert "source=admin" in caplog.text
    # сессия жива после отката
    assert (await db_session.execute(text("SELECT 1"))).scalar() == 1


@pytest.mark.asyncio
async def test_admin_save_writes_wave(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    first = (date.today() + timedelta(days=2)).isoformat()
    later = (date.today() + timedelta(days=9)).isoformat()
    body = {"starts_at_local": "11:00", "duration_minutes": 45, "kind": "public_skate"}
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r1 = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions", json={**body, "local_date": first}
            )
            assert r1.status_code == 200, r1.text
            r2 = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions", json={**body, "local_date": later}
            )
            assert r2.status_code == 200, r2.text
            # перенос сеанса ещё дальше — тоже волна (PATCH)
            further = (date.today() + timedelta(days=11)).isoformat()
            r3 = await client.patch(f"/api/webapp/admin/ice-sessions/{r2.json()['id']}", json={"local_date": further})
            assert r3.status_code == 200, r3.text
    rows = await _rows(db_session, arena_id)
    assert rows == [
        ("seed", None, date.fromisoformat(first)),
        ("admin", date.fromisoformat(first), date.fromisoformat(later)),
        ("admin", date.fromisoformat(later), date.fromisoformat(further)),
    ]


@pytest.mark.asyncio
async def test_admin_save_survives_wave_failure(app_use_test_db, db_session, monkeypatch) -> None:
    import src.application.schedule_waves as mod

    async def boom(*args, **kwargs):
        raise RuntimeError("waves down")

    monkeypatch.setattr(mod, "record_schedule_wave", boom)
    arena_id = await _arena(db_session)
    day = (date.today() + timedelta(days=2)).isoformat()
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/webapp/admin/arenas/{arena_id}/ice-sessions",
                json={"local_date": day, "starts_at_local": "11:00", "duration_minutes": 45},
            )
    assert r.status_code == 200, r.text
    saved = (
        await db_session.execute(text("SELECT count(*) FROM ice_sessions WHERE arena_id = :a"), {"a": arena_id})
    ).scalar_one()
    assert saved == 1


async def _wave(db_session, arena_id: int, moment: datetime, source: str = "parser") -> None:
    await db_session.execute(
        text("INSERT INTO ice_schedule_waves (arena_id, detected_at, source) VALUES (:a, :t, :s)"),
        {"a": arena_id, "t": moment, "s": source},
    )


@pytest.mark.asyncio
async def test_card_fields_default_and_habit(db_session) -> None:
    arena_id = await _arena(db_session)
    fields = await schedule_card_fields(db_session, arena_id, tz_name="Europe/Minsk", now=NOW)
    assert fields == {
        "schedule_habit": {"level": "none", "weekday": None},
        "schedule_horizon": None,
        "schedule_tracked": False,
    }

    await _ice(db_session, arena_id, D)
    # пятницы 16.10 и 23.10; seed (09.10), волна старше 42 дней (04.09) и «будущая» не в счёт
    await _wave(db_session, arena_id, datetime(2026, 10, 16, 15, 0, tzinfo=MINSK))
    await _wave(db_session, arena_id, datetime(2026, 10, 23, 15, 0, tzinfo=MINSK))
    await _wave(db_session, arena_id, datetime(2026, 10, 9, 15, 0, tzinfo=MINSK), source="seed")
    await _wave(db_session, arena_id, datetime(2026, 9, 4, 15, 0, tzinfo=MINSK))
    await _wave(db_session, arena_id, datetime(2026, 10, 30, 15, 0, tzinfo=MINSK))
    fields = await schedule_card_fields(db_session, arena_id, tz_name="Europe/Minsk", now=NOW)
    assert fields == {
        "schedule_habit": {"level": "week", "weekday": None},
        "schedule_horizon": "2026-10-25",
        "schedule_tracked": True,
    }

    await _wave(db_session, arena_id, datetime(2026, 10, 2, 15, 0, tzinfo=MINSK), source="backfill")
    fields = await schedule_card_fields(db_session, arena_id, tz_name="Europe/Minsk", now=NOW)
    assert fields["schedule_habit"] == {"level": "day", "weekday": 4}


@pytest.mark.asyncio
async def test_card_fields_fall_back_when_query_fails(db_session, monkeypatch) -> None:
    import src.application.schedule_waves as mod

    async def boom(*args, **kwargs):
        await db_session.execute(text("SELECT * FROM no_such_table_task329"))

    monkeypatch.setattr(mod, "load_card_inputs", boom)
    arena_id = await _arena(db_session)
    fields = await schedule_card_fields(db_session, arena_id, tz_name="Europe/Minsk", now=NOW)
    assert fields["schedule_habit"] == {"level": "none", "weekday": None}
    assert fields["schedule_tracked"] is False
    # savepoint откатил только сбойный запрос — сессия карточки жива
    assert (await db_session.execute(text("SELECT 1"))).scalar() == 1


@pytest.mark.asyncio
async def test_public_card_carries_schedule_fields(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    card = await get_public_arena_card(db_session, str(arena_id))
    assert card["schedule_habit"] == {"level": "none", "weekday": None}
    assert card["schedule_horizon"] is None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get(f"/api/public/arenas/{arena_id}")
    assert r.status_code == 200, r.text
    assert r.json()["schedule_habit"] == {"level": "none", "weekday": None}
    assert "schedule_horizon" in r.json()


@pytest.mark.asyncio
async def test_admin_recurrence_rematerialize_writes_wave(app_use_test_db, db_session) -> None:
    arena_id = await _arena(db_session)
    # серия начата 5 дней назад; rematerialize продлит её от сегодня на неделю дальше
    body = {
        "local_date": (date.today() - timedelta(days=5)).isoformat(),
        "starts_at_local": "11:00",
        "duration_minutes": 45,
        "repeat_weekly": True,
    }
    with patch_admin_principal():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(f"/api/webapp/admin/arenas/{arena_id}/ice-sessions", json=body)
            assert created.status_code == 200, created.text
            key = created.json()["recurrence_key"]
            again = await client.post(f"/api/webapp/admin/ice-sessions/recurrence/{key}/rematerialize")
            assert again.status_code == 200, again.text
            assert again.json()["created"] >= 1
    rows = await _rows(db_session, arena_id)
    assert [r[0] for r in rows] == ["seed", "admin"]
    assert rows[1][1] == rows[0][2] and rows[1][2] == rows[0][2] + timedelta(days=7)


@pytest.mark.asyncio
async def test_admin_recurrence_unknown_key_and_missing_arena(db_session) -> None:
    from src.application.schedule_waves import record_admin_wave_for_recurrence_after_commit

    assert await record_admin_wave_for_recurrence_after_commit(db_session, "no-such-key") is None
    assert await record_admin_wave_after_commit(db_session, None) is None


@pytest.mark.asyncio
async def test_admin_recurrence_lookup_failure_is_swallowed(db_session, monkeypatch, caplog) -> None:
    import src.application.schedule_waves as mod

    async def boom(*args, **kwargs):
        raise RuntimeError("lookup down")

    monkeypatch.setattr(mod, "arena_id_for_recurrence", boom)
    assert await mod.record_admin_wave_for_recurrence_after_commit(db_session, "k") is None
    assert "arena lookup failed" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["parser_job", "disabled_job", "wave", "session"])
async def test_card_fields_tracked_sources(db_session, source) -> None:
    """TASK-330: пустой карточке есть что обещать, только если каток ведёт расписание."""
    arena_id = await _arena(db_session)
    if source in ("parser_job", "disabled_job"):
        await db_session.execute(
            text(
                """
                INSERT INTO ice_parser_jobs (arena_id, parser_key, is_enabled, cadence, next_run_at, config)
                VALUES (:a, 'task330_test_v1', :on, 'daily', :t, CAST('{}' AS jsonb))
                """
            ),
            {"a": arena_id, "on": source == "parser_job", "t": NOW},
        )
    elif source == "wave":
        await _wave(db_session, arena_id, datetime(2026, 10, 9, 15, 0, tzinfo=MINSK), source="seed")
    else:
        await _ice(db_session, arena_id, D)
    fields = await schedule_card_fields(db_session, arena_id, tz_name="Europe/Minsk", now=NOW)
    assert fields["schedule_tracked"] is (source != "disabled_job")
