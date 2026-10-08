"""Trainer arena setup alternatives (mobile / legacy pending request gate)."""

import pytest
from sqlalchemy import text

from src.application.trainer_arena_setup_use_cases import (
    ARENA_WORK_FORMAT_MOBILE,
    ARENA_WORK_FORMAT_ONLINE,
    ARENA_WORK_FORMAT_PENDING_REQUEST,
    clear_trainer_arena_work_format,
    set_trainer_arena_mobile,
    set_trainer_arena_online,
    tt_minimal_arenas_satisfied,
)
from src.application.trainer_profile_completeness import analyze_tt_minimal_profile_readiness
from src.application.trainer_use_cases import create_trainer


def test_tt_minimal_arenas_satisfied_matrix() -> None:
    assert tt_minimal_arenas_satisfied({"arena_ids": [1]}) is True
    assert tt_minimal_arenas_satisfied({"arena_work_format": ARENA_WORK_FORMAT_MOBILE}) is True
    assert tt_minimal_arenas_satisfied(
        {
            "arena_work_format": ARENA_WORK_FORMAT_PENDING_REQUEST,
            "arena_request_text": "Arena",
        }
    )
    assert not tt_minimal_arenas_satisfied(
        {"arena_work_format": ARENA_WORK_FORMAT_PENDING_REQUEST, "arena_request_text": "  "}
    )


async def _minimal_trainer_id(db_session) -> int:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM cities ORDER BY id LIMIT 1"))
    cid = r2.scalar()
    if sid is None or cid is None:
        pytest.skip("need seed services and cities")
    return await create_trainer(
        db_session,
        profile={
            "first_name": "Ann",
            "last_name": "Xu",
            "phone": "+375291112233",
            "city_id": cid,
        },
        service_ids=[sid],
        arena_ids=[],
    )


@pytest.mark.asyncio
async def test_set_trainer_arena_mobile_persists(db_session) -> None:
    trainer_id = await _minimal_trainer_id(db_session)
    out = await set_trainer_arena_mobile(db_session, trainer_id)
    assert out is not None
    assert out.get("arena_work_format") == ARENA_WORK_FORMAT_MOBILE
    ok, miss = analyze_tt_minimal_profile_readiness(out)
    assert ok is True
    assert "arenas" not in miss


@pytest.mark.asyncio
async def test_clear_trainer_arena_work_format_undoes_online(db_session) -> None:
    trainer_id = await _minimal_trainer_id(db_session)
    on = await set_trainer_arena_online(db_session, trainer_id)
    assert on is not None
    assert on.get("arena_work_format") == ARENA_WORK_FORMAT_ONLINE
    cleared = await clear_trainer_arena_work_format(db_session, trainer_id)
    assert cleared is not None
    assert not (cleared.get("arena_work_format") or "").strip()


@pytest.mark.asyncio
async def test_set_trainer_arena_online_refuses_when_arenas_linked(db_session) -> None:
    r = await db_session.execute(text("SELECT id FROM services ORDER BY id LIMIT 1"))
    sid = r.scalar()
    r2 = await db_session.execute(text("SELECT id FROM arenas ORDER BY id LIMIT 1"))
    aid = r2.scalar()
    if sid is None or aid is None:
        pytest.skip("need service and arena")
    trainer_id = await create_trainer(
        db_session,
        profile={"first_name": "On", "last_name": "Line", "age": 30},
        service_ids=[int(sid)],
        arena_ids=[int(aid)],
    )
    with pytest.raises(ValueError, match="площадки"):
        await set_trainer_arena_online(db_session, trainer_id)
