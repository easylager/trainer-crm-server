"""TASK-029 S3: saving slots clears a stale snooze on slots-related rhythm hints."""
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.application.trainer_hint_dismissal_use_cases import (
    dismiss_rhythm_hint,
    get_active_snoozes,
)
from tests.api.test_webapp_trainer_schedule_integration import (
    _create_active_trainer,
    _fresh_trainer_telegram_id,
    patch_trainer_webapp_init,
)


@pytest.mark.asyncio
async def test_saving_slots_clears_slots_related_snoozes(app_use_test_db, db_session) -> None:
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)

    await dismiss_rhythm_hint(db_session, trainer_id, "open_loop_free_next")
    await dismiss_rhythm_hint(db_session, trainer_id, "template")  # not slots-related — must survive
    before = await get_active_snoozes(db_session, trainer_id)
    assert "open_loop_free_next" in before
    assert "template" in before

    d = date.today() + timedelta(days=40)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "start_hours": [10, 11],
                    "duration_minutes": 60,
                },
            )
    assert resp.status_code == 200

    after = await get_active_snoozes(db_session, trainer_id)
    assert "open_loop_free_next" not in after
    assert "template" in after, "unrelated snooze must not be cleared by a slot save"


@pytest.mark.asyncio
async def test_saving_slots_via_per_slot_mode_also_clears_slots_related_snoozes(
    app_use_test_db, db_session
) -> None:
    """Same reset, exercised through the other successful path: `slot_entries` (per-slot
    precise mode), not `start_hours` — both branches call `_clear_slot_related_hint_snoozes`."""
    tg = _fresh_trainer_telegram_id()
    trainer_id = await _create_active_trainer(db_session, tg, with_crm=True)

    await dismiss_rhythm_hint(db_session, trainer_id, "slots_next_week")
    await dismiss_rhythm_hint(db_session, trainer_id, "template")  # not slots-related — must survive
    before = await get_active_snoozes(db_session, trainer_id)
    assert "slots_next_week" in before
    assert "template" in before

    d = date.today() + timedelta(days=41)
    with patch_trainer_webapp_init(tg):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/webapp/schedule/slots",
                headers={"X-Telegram-Init-Data": "mock", "Content-Type": "application/json"},
                json={
                    "slot_date": d.isoformat(),
                    "slot_entries": [{"start_time": "10:00", "duration_minutes": 60}],
                },
            )
    assert resp.status_code == 200

    after = await get_active_snoozes(db_session, trainer_id)
    assert "slots_next_week" not in after
    assert "template" in after, "unrelated snooze must not be cleared by a slot save"
