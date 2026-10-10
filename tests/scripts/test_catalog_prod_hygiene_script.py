"""TASK-177: scripts/catalog_prod_hygiene.py against the test DB (step functions)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from scripts import catalog_prod_hygiene as hygiene
from src.shared.ops_db_guard import ProdDatabaseError
from tests.api.test_catalog_prod_hygiene import _raw_session, _status
from tests.api.test_public_arenas import _add_future_session, _insert_arena, _insert_bare_trainer, _insert_city


async def _profile(db_session, arena_id: int) -> str:
    return (
        await db_session.execute(text("SELECT status FROM arena_profiles WHERE arena_id = :id"), {"id": arena_id})
    ).scalar_one()


@pytest.mark.asyncio
async def test_test_arenas_dry_run_lists_and_apply_archives(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Скриптск {uuid.uuid4().hex[:6]}")
    test_arena = await _insert_arena(db_session, city_id, name="Тестовая Арена 1")
    await db_session.execute(
        text("UPDATE arena_profiles SET status = 'published' WHERE arena_id = :id"), {"id": test_arena}
    )
    real = await _insert_arena(db_session, city_id, name="Протестантский каток")
    plan = await hygiene.step_test_arenas(db_session, apply=False)
    assert any(f"#{test_arena} " in line and "-> 'archived'" in line for line in plan)
    assert not any(f"#{real} " in line for line in plan)
    assert await _profile(db_session, test_arena) == "published"

    await hygiene.step_test_arenas(db_session, apply=True)
    assert await _profile(db_session, test_arena) == "archived"
    assert await _profile(db_session, real) == "published"
    active = (
        await db_session.execute(text("SELECT is_active FROM arenas WHERE id = :id"), {"id": test_arena})
    ).scalar_one()
    assert active is True  # a trainer may still use it in their schedule


@pytest.mark.asyncio
async def test_duplicates_repoint_references_and_retire(app_use_test_db, db_session, monkeypatch) -> None:
    city_id = await _insert_city(db_session, name=f"Дубльск {uuid.uuid4().hex[:6]}")
    canon = await _insert_arena(db_session, city_id, name="ТЦ DiaMond city")
    dup = await _insert_arena(db_session, city_id, name="Даймонд сити")
    owns_ice = await _insert_arena(db_session, city_id, name="Даймонд с расписанием")
    await _add_future_session(db_session, owns_ice)
    trainer = await _insert_bare_trainer(db_session)
    other = await _insert_bare_trainer(db_session)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id) VALUES (:t, :d), (:o, :d), (:o, :c)"),
        {"t": trainer, "o": other, "d": dup, "c": canon},
    )
    await db_session.execute(text("UPDATE trainers SET primary_arena_id = :d WHERE id = :t"), {"d": dup, "t": trainer})
    monkeypatch.setattr(
        hygiene,
        "DUPLICATES",
        (
            hygiene.Duplicate(dup, canon, "Даймонд", "test pair"),
            hygiene.Duplicate(owns_ice, canon, "Даймонд", "has sessions"),
            hygiene.Duplicate(canon, dup, "Замок", "name mismatch"),
        ),
    )
    plan = await hygiene.step_duplicates(db_session, apply=False, migrated=True)
    assert "'Даймонд сити' -> 'ТЦ DiaMond city'" in plan[0]
    assert "trainers.primary_arena_id=1" in plan[0]
    assert "SKIP — duplicate owns ice data" in plan[1]
    assert "SKIP — name" in plan[2]

    await hygiene.step_duplicates(db_session, apply=True, migrated=True)
    row = (
        await db_session.execute(
            text("SELECT is_active, merged_into_arena_id FROM arenas WHERE id = :id"), {"id": dup}
        )
    ).one()
    assert row == (False, canon)
    assert await _profile(db_session, dup) == "archived"
    links = (
        await db_session.execute(
            text("SELECT trainer_id, arena_id FROM trainer_arenas WHERE trainer_id IN (:t, :o) ORDER BY 1, 2"),
            {"t": trainer, "o": other},
        )
    ).all()
    assert sorted(links) == sorted([(trainer, canon), (other, canon)])
    prim = (
        await db_session.execute(text("SELECT primary_arena_id FROM trainers WHERE id = :t"), {"t": trainer})
    ).scalar_one()
    assert prim == canon
    untouched = (
        await db_session.execute(text("SELECT merged_into_arena_id FROM arenas WHERE id = :id"), {"id": owns_ice})
    ).scalar_one()
    assert untouched is None


@pytest.mark.asyncio
async def test_past_sessions_step_expires_only_older_than_a_day(app_use_test_db, db_session) -> None:
    city_id = await _insert_city(db_session, name=f"Сеансск {uuid.uuid4().hex[:6]}")
    arena_id = await _insert_arena(db_session, city_id, name="Каток сеансов")
    old = await _raw_session(db_session, arena_id, ends_ago=timedelta(days=2))
    recent = await _raw_session(db_session, arena_id, ends_ago=timedelta(hours=2))
    now = datetime.now(timezone.utc)
    plan = await hygiene.step_past_sessions(db_session, apply=False, now=now)
    assert any("BY:" in line for line in plan)
    assert await _status(db_session, old) == "active"
    await hygiene.step_past_sessions(db_session, apply=True, now=now)
    assert await _status(db_session, old) == "expired"
    assert await _status(db_session, recent) == "active"


def test_cloud_url_refused_without_prod_ack() -> None:
    with pytest.raises(ProdDatabaseError):
        hygiene.assert_database_url(
            "postgresql://u:p@x.proxy.rlwy.net.railway.app:5432/railway", apply=False, allow_prod=False
        )


def test_script_expiry_rule_matches_ttl_loop() -> None:
    from src.ingestion.ttl import SESSION_EXPIRE_AFTER

    assert hygiene.SESSION_EXPIRE_AFTER == SESSION_EXPIRE_AFTER
