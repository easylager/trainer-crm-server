"""Client invite bind: CRM roster + registration form gate."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import trainer_client_roster_link_exists
from src.application.client_invite_use_cases import (
    bind_client_invite_trainer_context,
    client_invite_needs_registration_form,
)


async def _seed_trainer(session: AsyncSession) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO trainers (status, schedule_grid_step_minutes, telegram_id)
            VALUES ('active', 15, 700001)
            RETURNING id
            """
        )
    )
    return int(r.scalar_one())


async def _seed_client_with_phone(
    session: AsyncSession,
    *,
    telegram_id: int = 800001,
    first_name: str = "Anna",
    phone: str = "+375291234567",
) -> int:
    r = await session.execute(
        text(
            """
            INSERT INTO clients (
                first_name, phone, phone_normalized, telegram_id, is_sandbox
            )
            VALUES (:fn, :phone, :phone, :tid, false)
            RETURNING id
            """
        ),
        {"fn": first_name, "phone": phone, "tid": telegram_id},
    )
    return int(r.scalar_one())


@pytest.mark.asyncio
async def test_needs_registration_when_phone_missing(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, telegram_id, is_sandbox)
            VALUES ('Bob', 800002, false)
            """
        )
    )
    await db_session.commit()
    assert await client_invite_needs_registration_form(db_session, 800002) is True


@pytest.mark.asyncio
async def test_needs_registration_when_first_name_missing(db_session: AsyncSession) -> None:
    await db_session.execute(
        text(
            """
            INSERT INTO clients (
                phone, phone_normalized, telegram_id, is_sandbox
            )
            VALUES ('+375299999999', '+375299999999', 800003, false)
            """
        )
    )
    await db_session.commit()
    assert await client_invite_needs_registration_form(db_session, 800003) is True


@pytest.mark.asyncio
async def test_needs_registration_false_when_profile_complete(
    db_session: AsyncSession,
) -> None:
    await _seed_client_with_phone(db_session, telegram_id=800004)
    await db_session.commit()
    assert await client_invite_needs_registration_form(db_session, 800004) is False


@pytest.mark.asyncio
async def test_bind_invite_creates_roster_for_existing_client(
    db_session: AsyncSession,
) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client_with_phone(db_session, telegram_id=800005)
    await db_session.commit()

    assert not await trainer_client_roster_link_exists(db_session, trainer_id, client_id)

    await bind_client_invite_trainer_context(
        800005, trainer_id, db_session, client_id=client_id
    )

    assert await trainer_client_roster_link_exists(db_session, trainer_id, client_id)


@pytest.mark.asyncio
async def test_bind_invite_notifies_trainer_on_new_roster(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client_with_phone(db_session, telegram_id=800006)
    await db_session.commit()

    calls: list[dict] = []

    async def _capture_notify(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "src.application.client_invite_use_cases.notify_trainer_client_registered_from_invite",
        _capture_notify,
    )

    await bind_client_invite_trainer_context(
        800006, trainer_id, db_session, client_id=client_id
    )

    assert len(calls) == 1
    assert calls[0]["trainer_id"] == trainer_id
    assert calls[0]["client_id"] == client_id
    assert calls[0]["event"] == "new_client"


@pytest.mark.asyncio
async def test_bind_invite_skips_notify_when_roster_already_exists(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trainer_id = await _seed_trainer(db_session)
    client_id = await _seed_client_with_phone(db_session, telegram_id=800007)
    await db_session.execute(
        text(
            """
            INSERT INTO trainer_client_roster (trainer_id, client_id)
            VALUES (:tid, :cid)
            """
        ),
        {"tid": trainer_id, "cid": client_id},
    )
    await db_session.commit()

    calls: list[dict] = []

    async def _capture_notify(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(
        "src.application.client_invite_use_cases.notify_trainer_client_registered_from_invite",
        _capture_notify,
    )

    await bind_client_invite_trainer_context(
        800007, trainer_id, db_session, client_id=client_id
    )

    assert calls == []
