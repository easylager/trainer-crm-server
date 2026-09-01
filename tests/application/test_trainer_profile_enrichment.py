"""Profile enrichment nudges: pure picker + SQL audience (no Telegram)."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from src.application.trainer_profile_enrichment_use_cases import (
    _pick_due_step,
    render_profile_enrichment_nudge_text,
)
from src.infrastructure.db.models import (
    PROFILE_NUDGE_STEP_P1,
    PROFILE_NUDGE_STEP_P8,
    PROFILE_NUDGE_STEP_P21,
)


def test_before_first_day_yields_none() -> None:
    assert _pick_due_step(days_since_first_booking=0, already_sent=frozenset()) is None


def test_day_one_picks_playful_opener() -> None:
    assert _pick_due_step(days_since_first_booking=1, already_sent=frozenset()) == (
        PROFILE_NUDGE_STEP_P1,
        1,
    )


def test_week_later_picks_p8_if_p1_already_sent() -> None:
    assert _pick_due_step(
        days_since_first_booking=8, already_sent=frozenset({PROFILE_NUDGE_STEP_P1})
    ) == (PROFILE_NUDGE_STEP_P8, 8)


def test_late_tick_fast_forwards_to_last_step() -> None:
    assert _pick_due_step(days_since_first_booking=40, already_sent=frozenset()) == (
        PROFILE_NUDGE_STEP_P21,
        21,
    )


def test_series_exhausted_is_silent() -> None:
    assert (
        _pick_due_step(
            days_since_first_booking=40,
            already_sent=frozenset(
                {PROFILE_NUDGE_STEP_P1, PROFILE_NUDGE_STEP_P8, PROFILE_NUDGE_STEP_P21}
            ),
        )
        is None
    )


def test_copy_says_what_to_do_without_urgency() -> None:
    t1 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P1)
    t8 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P8)
    t21 = render_profile_enrichment_nudge_text(PROFILE_NUDGE_STEP_P21)
    blob = (t1 + t8 + t21).lower()
    assert "цену занятия" in t1.lower()
    assert "профил" in blob
    assert "тариф" in blob
    assert "не входит" in blob
    for forbidden in ("заполни", "срочно", "добить", "обязательн", "почём", "почем"):
        assert forbidden not in blob


def test_nudge_has_open_profile_button_label() -> None:
    from src.bot import messages as msg

    assert msg.TRAINER_PROFILE_ENRICH_NUDGE_BTN == "Открыть профиль"


async def _trainer_with_booking(
    db_session,
    *,
    price_cents: int | None,
    status: str = "pending_profile",
    days_ago: int = 2,
) -> int:
    from datetime import date, datetime, time, timedelta, timezone

    from tests.conftest import belarus_test_phone, unique_test_telegram_id
    from tests.db_catalog_helpers import require_seed_service_id

    service_id = await require_seed_service_id(db_session)
    trainer_tg = unique_test_telegram_id()
    r = await db_session.execute(
        text("INSERT INTO trainers (status, telegram_id) VALUES (:st, :tg) RETURNING id"),
        {"st": status, "tg": trainer_tg},
    )
    trainer_id = int(r.fetchone()[0])
    await db_session.execute(
        text(
            "INSERT INTO trainer_services (trainer_id, service_id, price_cents) "
            "VALUES (:tid, :sid, :price)"
        ),
        {"tid": trainer_id, "sid": service_id, "price": price_cents},
    )
    client_tg = unique_test_telegram_id()
    phone, pn = belarus_test_phone(client_tg)
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, first_name, phone, phone_normalized)
            VALUES (:tg, 'Ученик', :phone, :pn) RETURNING id
            """
        ),
        {"tg": client_tg, "phone": phone, "pn": pn},
    )
    client_id = int(r.fetchone()[0])
    slot_day = date.today() + timedelta(days=3)
    r = await db_session.execute(
        text(
            """
            INSERT INTO slots (trainer_id, slot_date, start_time, end_time, status)
            VALUES (:tid, :d, :st, :en, 'booked') RETURNING id
            """
        ),
        {"tid": trainer_id, "d": slot_day, "st": time(10, 0), "en": time(11, 0)},
    )
    slot_id = int(r.fetchone()[0])
    created = datetime.now(timezone.utc) - timedelta(days=days_ago)
    await db_session.execute(
        text(
            """
            INSERT INTO bookings (slot_id, trainer_id, client_id, service_id, status, created_at)
            VALUES (:sid, :tid, :cid, :svc, 'confirmed', :created)
            """
        ),
        {
            "sid": slot_id,
            "tid": trainer_id,
            "cid": client_id,
            "svc": service_id,
            "created": created,
        },
    )
    await db_session.commit()
    return trainer_id


@pytest.mark.asyncio
async def test_sql_audience_includes_unpriced_trainer_with_a_real_booking(app_use_test_db, db_session) -> None:
    from src.application.trainer_profile_enrichment_use_cases import list_profile_enrichment_candidates

    trainer_id = await _trainer_with_booking(db_session, price_cents=None)
    ids = {c["trainer_id"] for c in await list_profile_enrichment_candidates(db_session)}
    assert trainer_id in ids


@pytest.mark.asyncio
async def test_sql_audience_drops_trainer_once_a_tariff_exists(app_use_test_db, db_session) -> None:
    from src.application.trainer_profile_enrichment_use_cases import list_profile_enrichment_candidates

    trainer_id = await _trainer_with_booking(db_session, price_cents=4500)
    ids = {c["trainer_id"] for c in await list_profile_enrichment_candidates(db_session)}
    assert trainer_id not in ids


@pytest.mark.asyncio
async def test_sql_audience_ignores_deactivated_trainers(app_use_test_db, db_session) -> None:
    from src.application.trainer_profile_enrichment_use_cases import list_profile_enrichment_candidates

    trainer_id = await _trainer_with_booking(
        db_session, price_cents=None, status="deactivated"
    )
    ids = {c["trainer_id"] for c in await list_profile_enrichment_candidates(db_session)}
    assert trainer_id not in ids


@pytest.mark.asyncio
async def test_due_nudge_on_day_two_is_the_playful_opener(app_use_test_db, db_session) -> None:
    from src.application.trainer_profile_enrichment_use_cases import compute_due_profile_enrichment_nudges
    from src.infrastructure.db.models import PROFILE_NUDGE_STEP_P1

    trainer_id = await _trainer_with_booking(db_session, price_cents=None, days_ago=2)
    due = await compute_due_profile_enrichment_nudges(db_session)
    mine = [d for d in due if d.trainer_id == trainer_id]
    assert len(mine) == 1
    assert mine[0].step == PROFILE_NUDGE_STEP_P1

