import pytest
from sqlalchemy import text

from src.application.trainer_use_cases import (
    create_trainer,
    create_trainer_education,
    moderate_trainer_education_for_profile,
    update_trainer_education,
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


@pytest.mark.asyncio
async def test_create_education_double_submit_does_not_duplicate(db_session) -> None:
    """
    Double tap / retried request submitting the identical new entry twice must not create
    two visible rows (regression: prod trainer_id=11 ended up with 2-3 identical cards).
    """
    trainer_id = await create_trainer(db_session, profile={"first_name": "Макс", "last_name": "Тренер", "age": 31})
    payload = {
        "education_type": "formal_education",
        "institution_name": "БГУФК",
        "program_or_title": "Тренер по хоккею и физической культуре",
        "country": "Беларусь",
        "city": "Минск",
        "start_year": 2020,
        "end_year": 2024,
    }
    first = await create_trainer_education(db_session, trainer_id, payload=payload)
    second = await create_trainer_education(db_session, trainer_id, payload=payload)
    assert first["id"] == second["id"]
    row = await db_session.execute(
        text("SELECT count(*) FROM trainer_education WHERE trainer_id = :tid"),
        {"tid": trainer_id},
    )
    assert row.scalar() == 1


@pytest.mark.asyncio
async def test_edit_approved_education_double_submit_does_not_duplicate_revision(db_session) -> None:
    """
    Editing an approved entry creates a pending revision (supersedes the approved row).
    A double-submitted identical edit must reuse that same revision, not create a second
    pending row superseding the same approved entry.
    """
    trainer_id = await create_trainer(db_session, profile={"first_name": "Оля", "last_name": "Тренер", "age": 28})
    created = await create_trainer_education(
        db_session,
        trainer_id,
        payload={
            "education_type": "formal_education",
            "institution_name": "БГУФК",
            "program_or_title": "Тренер",
        },
    )
    education_id = created["id"]
    await moderate_trainer_education_for_profile(
        db_session, trainer_id, decision="approved", admin_id=1
    )
    edit_payload = {"city": "Минск", "start_year": 2021, "end_year": 2025}
    r1 = await update_trainer_education(db_session, trainer_id, education_id, payload=edit_payload)
    r2 = await update_trainer_education(db_session, trainer_id, education_id, payload=edit_payload)
    assert r1["revision_created"] is True
    assert r2["revision_created"] is True
    assert r1["id"] == r2["id"]
    row = await db_session.execute(
        text(
            "SELECT count(*) FROM trainer_education WHERE trainer_id = :tid AND supersedes_id = :eid"
        ),
        {"tid": trainer_id, "eid": education_id},
    )
    assert row.scalar() == 1
