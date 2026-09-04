"""Trainer arena setup alternatives (mobile / legacy pending request gate)."""

import pytest
from sqlalchemy import text

from src.application.trainer_arena_setup_use_cases import (
    ARENA_WORK_FORMAT_MOBILE,
    ARENA_WORK_FORMAT_PENDING_REQUEST,
    set_trainer_arena_mobile,
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
