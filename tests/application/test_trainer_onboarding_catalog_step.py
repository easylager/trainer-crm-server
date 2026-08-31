"""TASK-007: checklist exposes «отправлено на модерацию» so the hub strip can hold step 3.

`profile_complete` only means the 8 submission criteria are met — it says nothing about
whether the trainer actually pressed submit. The strip must not disappear on readiness alone,
so the payload carries a separate `moderation_submitted` flag.
"""
from datetime import datetime, timezone


from sqlalchemy import text

from src.application.trainer_onboarding_checklist import get_trainer_onboarding_checklist


async def _seed_trainer(db_session, *, status: str, moderation_submitted_at=None) -> int:
    now = datetime.now(timezone.utc)
    r = await db_session.execute(
        text(
            "INSERT INTO trainers (status, created_at, moderation_submitted_at) "
            "VALUES (:status, :now, :sub) RETURNING id"
        ),
        {"status": status, "now": now, "sub": moderation_submitted_at},
    )
    tid = int(r.scalar_one())
    await db_session.commit()
    return tid


async def test_checklist_reports_not_submitted_for_fresh_pending_trainer(db_session):
    """Bare pending_profile trainer: flag present and False — strip keeps step 3 open."""
    tid = await _seed_trainer(db_session, status="pending_profile")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)

    assert checklist is not None
    assert "moderation_submitted" in checklist, "hub strip depends on this key existing"
    assert checklist["moderation_submitted"] is False


async def test_checklist_moderation_submitted_is_independent_of_profile_complete(db_session):
    """Readiness (8 criteria) must not be mistaken for submission — that conflation is the bug."""
    tid = await _seed_trainer(db_session, status="pending_profile")

    checklist = await get_trainer_onboarding_checklist(db_session, tid)

    assert checklist is not None
    # An empty trainer row is neither ready nor submitted; the point is that the two are
    # distinct keys, so the strip can tell «можно отправить» from «уже отправлено».
    assert checklist["profile_complete"] is False
    assert checklist["moderation_submitted"] is False
