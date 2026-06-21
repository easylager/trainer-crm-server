"""CRM client names must not be overwritten by Telegram display names."""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.client_use_cases import get_or_create_client


@pytest.mark.asyncio
async def test_get_or_create_client_preserves_existing_first_name(
    db_session: AsyncSession,
) -> None:
    telegram_id = 810001
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (first_name, last_name, telegram_id, is_sandbox)
            VALUES ('Иван', 'Владикс', :tid, false)
            RETURNING id
            """
        ),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()

    same_id = await get_or_create_client(
        db_session,
        telegram_id,
        first_name="Максим🪴",
        last_name="TelegramLast",
        telegram_username="maxdev",
    )
    await db_session.commit()

    assert same_id == client_id
    row = (
        await db_session.execute(
            text(
                """
                SELECT first_name, last_name, telegram_username
                FROM clients WHERE id = :cid
                """
            ),
            {"cid": client_id},
        )
    ).one()
    assert row[0] == "Иван"
    assert row[1] == "Владикс"
    assert row[2] == "maxdev"


@pytest.mark.asyncio
async def test_get_or_create_client_fills_empty_name_from_telegram(
    db_session: AsyncSession,
) -> None:
    telegram_id = 810002
    r = await db_session.execute(
        text(
            """
            INSERT INTO clients (telegram_id, is_sandbox)
            VALUES (:tid, false)
            RETURNING id
            """
        ),
        {"tid": telegram_id},
    )
    client_id = int(r.scalar_one())
    await db_session.commit()

    await get_or_create_client(
        db_session,
        telegram_id,
        first_name="Anna",
        last_name="Smith",
    )
    await db_session.commit()

    row = (
        await db_session.execute(
            text("SELECT first_name, last_name FROM clients WHERE id = :cid"),
            {"cid": client_id},
        )
    ).one()
    assert row[0] == "Anna"
    assert row[1] == "Smith"
