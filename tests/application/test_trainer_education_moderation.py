import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    create_trainer_education,
    moderate_trainer_education_for_profile,
)


@pytest.mark.asyncio
async def test_reject_requires_reason(db_session) -> None:
    """Rejected moderation decision must contain reason."""
    trainer_id = await create_trainer(db_session, profile={"first_name": "Тест", "last_name": "Тренер", "age": 30})
    await create_trainer_education(
        db_session,
        trainer_id,
        payload={
            "education_type": "formal_education",
            "institution_name": "БГУФК",
            "program_or_title": "Тренер",
        },
    )
    with pytest.raises(ValueError):
        await moderate_trainer_education_for_profile(
            db_session,
            trainer_id,
            decision="rejected",
            admin_id=100500,
            reason="",
        )


@pytest.mark.asyncio
async def test_approve_writes_moderation_events(db_session) -> None:
    """Approve decision updates status and writes moderation audit events."""
    trainer_id = await create_trainer(db_session, profile={"first_name": "Иван", "last_name": "Тренер", "age": 29})
    await create_trainer_education(
        db_session,
        trainer_id,
        payload={
            "education_type": "formal_education",
            "institution_name": "БГУ",
            "program_or_title": "Физическая культура",
        },
    )
    affected = await moderate_trainer_education_for_profile(
        db_session,
        trainer_id,
        decision="approved",
        admin_id=777,
    )
    assert affected == 1
    row = await db_session.execute(
        text(
            """
            SELECT moderation_status, approved_snapshot
            FROM trainer_education
            WHERE trainer_id = :tid
            """
        ),
        {"tid": trainer_id},
    )
    status_row = row.fetchone()
    assert status_row is not None
    assert status_row[0] == "approved"
    assert bool(status_row[1]) is True
    ev = await db_session.execute(
        text(
            """
            SELECT decision, admin_id
            FROM trainer_education_moderation_events
            ORDER BY id DESC
            LIMIT 1
            """
        )
    )
    ev_row = ev.fetchone()
    assert ev_row is not None
    assert ev_row[0] == "approved"
    assert int(ev_row[1]) == 777
