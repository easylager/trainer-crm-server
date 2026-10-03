"""Hub invite gate must drop once the client finishes registration.

A welcome_ref start stores pending_referral_trainer_id and nothing else.
Clearing that flag used to pass an empty payload as None, and the session
upsert treats None as "leave the column alone" — so the hub kept showing
«Вас пригласил тренер» after the profile was already saved.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_invite_use_cases import pending_referral_for_hub
from src.application.client_session_use_cases import (
    clear_pending_referral,
    clear_pending_request_id,
    get_pending_referral,
    set_pending_referral,
    set_pending_request_id,
)


async def _payload(session: AsyncSession, telegram_id: int) -> dict | None:
    row = (
        await session.execute(
            text("SELECT payload FROM client_sessions WHERE telegram_id = :tid"),
            {"tid": telegram_id},
        )
    ).scalar_one()
    return row


@pytest.mark.asyncio
async def test_clear_pending_referral_when_it_is_the_only_payload_key(
    db_session: AsyncSession,
) -> None:
    telegram_id = 881001
    await set_pending_referral(telegram_id, 42, db_session)
    assert await get_pending_referral(telegram_id, db_session) == 42

    await clear_pending_referral(telegram_id, db_session)

    assert await get_pending_referral(telegram_id, db_session) is None
    stored = await _payload(db_session, telegram_id)
    assert stored is None or "pending_referral_trainer_id" not in stored


@pytest.mark.asyncio
async def test_clear_pending_referral_keeps_other_payload_keys(
    db_session: AsyncSession,
) -> None:
    telegram_id = 881002
    await db_session.execute(
        text(
            """
            INSERT INTO client_sessions (telegram_id, state, payload)
            VALUES (:tid, 'idle', CAST(:payload AS jsonb))
            """
        ),
        {
            "tid": telegram_id,
            "payload": '{"pending_referral_trainer_id": 7, "pending_request_id": 15}',
        },
    )
    await db_session.commit()

    await clear_pending_referral(telegram_id, db_session)

    assert await get_pending_referral(telegram_id, db_session) is None
    stored = await _payload(db_session, telegram_id)
    assert stored is not None
    assert stored.get("pending_request_id") == 15
    assert "pending_referral_trainer_id" not in stored


@pytest.mark.asyncio
async def test_hub_does_not_gate_a_client_who_already_registered(
    db_session: AsyncSession,
) -> None:
    telegram_id = 881003
    await db_session.execute(
        text(
            """
            INSERT INTO clients (
                first_name, phone, phone_normalized, telegram_id, is_sandbox
            )
            VALUES ('Anna', '+375291112233', '+375291112233', :tid, false)
            """
        ),
        {"tid": telegram_id},
    )
    await db_session.commit()
    await set_pending_referral(telegram_id, 42, db_session)

    gate = await pending_referral_for_hub(db_session, telegram_id)

    assert gate is None
    assert await get_pending_referral(telegram_id, db_session) is None


@pytest.mark.asyncio
async def test_hub_still_gates_until_phone_and_name_exist(
    db_session: AsyncSession,
) -> None:
    telegram_id = 881004
    await set_pending_referral(telegram_id, 42, db_session)

    gate = await pending_referral_for_hub(db_session, telegram_id)

    assert gate == 42


@pytest.mark.asyncio
async def test_clear_pending_request_when_it_is_the_only_payload_key(
    db_session: AsyncSession,
) -> None:
    telegram_id = 881005
    await set_pending_request_id(telegram_id, 15, db_session)
    await clear_pending_request_id(telegram_id, db_session)
    stored = await _payload(db_session, telegram_id)
    assert stored is None or "pending_request_id" not in (stored or {})
