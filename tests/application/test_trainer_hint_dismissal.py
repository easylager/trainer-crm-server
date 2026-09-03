"""TASK-029: server-side snooze for hub rhythm hints (S1)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.trainer_hint_dismissal_use_cases import (
    DISMISSIBLE_HINT_IDS,
    NON_DISMISSIBLE_URGENT_HINT_IDS,
    clear_hint_snoozes,
    dismiss_rhythm_hint,
    get_active_snoozes,
)


async def _seed_trainer(db_session) -> int:
    r = await db_session.execute(
        text("INSERT INTO trainers (status) VALUES ('active') RETURNING id")
    )
    tid = int(r.scalar_one())
    await db_session.commit()
    return tid


async def test_dismiss_rhythm_hint_sets_future_snooze(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await dismiss_rhythm_hint(db_session, tid, "referral_growth")

    active = await get_active_snoozes(db_session, tid)
    assert "referral_growth" in active
    assert active["referral_growth"] > datetime.now(timezone.utc)


async def test_dismiss_rhythm_hint_rejects_urgent_ids() -> None:
    for hint_id in NON_DISMISSIBLE_URGENT_HINT_IDS:
        assert hint_id not in DISMISSIBLE_HINT_IDS


@pytest.mark.parametrize("hint_id", ["open_loop_no_next", "slots_this_week", "made_up_hint"])
async def test_dismiss_rhythm_hint_raises_for_non_dismissible(db_session, hint_id: str) -> None:
    tid = await _seed_trainer(db_session)
    with pytest.raises(ValueError):
        await dismiss_rhythm_hint(db_session, tid, hint_id)


async def test_dismiss_rhythm_hint_repeat_pushes_snooze_forward(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await dismiss_rhythm_hint(db_session, tid, "template")
    first = (await get_active_snoozes(db_session, tid))["template"]

    # Simulate the snooze having almost expired, then dismiss again — should push forward.
    await db_session.execute(
        text(
            "UPDATE trainer_hint_dismissals SET snooze_until = :t "
            "WHERE trainer_id = :tid AND hint_id = 'template'"
        ),
        {"t": datetime.now(timezone.utc) + timedelta(minutes=1), "tid": tid},
    )
    await db_session.commit()
    await dismiss_rhythm_hint(db_session, tid, "template")
    second = (await get_active_snoozes(db_session, tid))["template"]
    assert second > first - timedelta(minutes=1)  # meaningfully further out again


async def test_get_active_snoozes_excludes_expired(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_hint_dismissals (trainer_id, hint_id, snooze_until)
            VALUES (:tid, 'client_notes', :past)
            """
        ),
        {"tid": tid, "past": datetime.now(timezone.utc) - timedelta(days=1)},
    )
    await db_session.commit()

    active = await get_active_snoozes(db_session, tid)
    assert "client_notes" not in active


async def test_clear_hint_snoozes_removes_rows(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await dismiss_rhythm_hint(db_session, tid, "slots_next_week")
    await dismiss_rhythm_hint(db_session, tid, "open_loop_free_next")

    await clear_hint_snoozes(db_session, tid, ["slots_next_week", "open_loop_free_next"])

    active = await get_active_snoozes(db_session, tid)
    assert "slots_next_week" not in active
    assert "open_loop_free_next" not in active


async def test_clear_hint_snoozes_noop_on_empty_list(db_session) -> None:
    tid = await _seed_trainer(db_session)
    await dismiss_rhythm_hint(db_session, tid, "template")
    await clear_hint_snoozes(db_session, tid, [])
    active = await get_active_snoozes(db_session, tid)
    assert "template" in active
