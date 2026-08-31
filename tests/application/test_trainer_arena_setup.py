"""Trainer arena setup alternatives (mobile / pending request)."""

import pytest
from sqlalchemy import text

from src.application.trainer_arena_setup_use_cases import (
    ARENA_WORK_FORMAT_MOBILE,
    ARENA_WORK_FORMAT_PENDING_REQUEST,
    set_trainer_arena_mobile,
    submit_trainer_arena_request,
    tt_minimal_arenas_satisfied,
)
from src.application.trainer_profile_completeness import analyze_tt_minimal_profile_readiness
from src.application.trainer_use_cases import create_trainer, get_trainer


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
async def test_submit_arena_request_creates_support_ticket(db_session, monkeypatch) -> None:
    trainer_id = await _minimal_trainer_id(db_session)
    captured: list[dict] = []

    async def _fake_support(session, telegram_id, from_role, message_text, **kwargs):
        captured.append(
            {
                "telegram_id": telegram_id,
                "from_role": from_role,
                "message_text": message_text,
                "tag": kwargs.get("admin_notify_source_tag"),
            }
        )
        return {"id": 99, "ok": True}

    monkeypatch.setattr(
        "src.application.trainer_arena_setup_use_cases.create_support_message",
        _fake_support,
    )

    out = await submit_trainer_arena_request(
        db_session,
        trainer_id,
        arena_name="Ледовый дворец",
        note="ул. Примерная, 1",
        telegram_id=123456,
    )
    assert out is not None
    assert out.get("arena_work_format") == ARENA_WORK_FORMAT_PENDING_REQUEST
    assert "Ледовый дворец" in (out.get("arena_request_text") or "")
    assert len(captured) == 1
    assert captured[0]["telegram_id"] == 123456
    assert "Ледовый дворец" in captured[0]["message_text"]

    row = await get_trainer(db_session, trainer_id)
    assert row is not None
    assert row.get("arena_work_format") == ARENA_WORK_FORMAT_PENDING_REQUEST
