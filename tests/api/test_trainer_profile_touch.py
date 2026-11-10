"""Миграция 0317: услуги, цены, абонементы и катки тренера двигают ``trainer_profiles.updated_at``."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from tests.api.test_public_place_page import _place
from tests.api.test_site_trainers import _client, _trainer_on

OLD = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _stamp(db, tid: int) -> datetime:
    return (
        await db.execute(text("SELECT updated_at FROM trainer_profiles WHERE trainer_id = :t"), {"t": tid})
    ).scalar_one()


async def _reset(db, tid: int) -> None:
    await db.execute(text("UPDATE trainer_profiles SET updated_at = :o WHERE trainer_id = :t"), {"o": OLD, "t": tid})
    assert await _stamp(db, tid) == OLD


@pytest.mark.asyncio
async def test_offer_changes_bump_the_profile_and_cosmetics_do_not(app_use_test_db, db_session) -> None:
    place = await _place(db_session)
    async with _client() as client:
        tid = await _trainer_on(db_session, client, place, first_name="Метка")
    params = {"t": tid}

    # Не видно на сайте: акцент кнопки и текст-уведомление услуги.
    await _reset(db_session, tid)
    await db_session.execute(
        text("UPDATE trainer_services SET ui_accent = 'mint', client_notice = 'привет' WHERE trainer_id = :t"), params
    )
    assert await _stamp(db_session, tid) == OLD

    # Цена услуги, групповая, тариф, описание — видно.
    for sql in (
        "UPDATE trainer_services SET price_cents = 6100 WHERE trainer_id = :t",
        "UPDATE trainer_services SET group_price_cents = 2200 WHERE trainer_id = :t",
        "UPDATE trainer_service_price_variants SET price_cents = price_cents + 50 WHERE trainer_id = :t",
        "UPDATE trainer_pass_products SET price_cents = price_cents + 100 WHERE trainer_id = :t AND is_active",
        "UPDATE trainer_arenas SET is_public = false WHERE trainer_id = :t",
        "DELETE FROM trainer_arenas WHERE trainer_id = :t",
        "DELETE FROM trainer_service_price_variants WHERE trainer_id = :t",
        "DELETE FROM trainer_services WHERE trainer_id = :t",
    ):
        await _reset(db_session, tid)
        await db_session.execute(text(sql), params)
        assert await _stamp(db_session, tid) > OLD, sql

    # Новая связь с катком — тоже.
    await _reset(db_session, tid)
    await db_session.execute(
        text("INSERT INTO trainer_arenas (trainer_id, arena_id, is_public) VALUES (:t, :a, true)"),
        {"t": tid, "a": place["arena_id"]},
    )
    assert await _stamp(db_session, tid) > OLD
