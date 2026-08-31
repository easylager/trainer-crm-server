"""Share-catalog tip: pending/non-active trainer must still get the personal deep link (TASK-006)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import src.infrastructure.db as db_pkg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.share_catalog_tip import send_trainer_share_catalog_tip_to_chat
from tests.db_catalog_helpers import require_seed_service_id


async def _create_pending_trainer_with_city(session: AsyncSession) -> int:
    service_id = await require_seed_service_id(session)
    r = await session.execute(text("SELECT id FROM cities LIMIT 1"))
    row = r.fetchone()
    if row is None:
        r2 = await session.execute(
            text("INSERT INTO cities (name) VALUES ('Test City') RETURNING id")
        )
        city_id = int(r2.scalar_one())
    else:
        city_id = int(row[0])
    r3 = await session.execute(
        text("INSERT INTO trainers (status) VALUES ('pending_profile') RETURNING id")
    )
    trainer_id = int(r3.scalar_one())
    await session.execute(
        text(
            "INSERT INTO trainer_profiles (trainer_id, first_name, last_name, age, city_id) "
            "VALUES (:tid, 'Test', 'Trainer', 25, :cid)"
        ),
        {"tid": trainer_id, "cid": city_id},
    )
    await session.execute(
        text("INSERT INTO trainer_services (trainer_id, service_id, price_cents) VALUES (:tid, :sid, 5000)"),
        {"tid": trainer_id, "sid": service_id},
    )
    await session.commit()
    return trainer_id


@pytest.mark.asyncio
async def test_pending_trainer_gets_deep_link_instead_of_silent_skip(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for TASK-006 bug (b): pending/non-active trainer must receive the
    personal deep-link tip instead of the function silently returning.

    share_catalog_tip.py does ``from src.infrastructure.db import async_session_factory``,
    a local binding conftest's module-wide patch doesn't reach (see conftest.py
    _apply_test_session_factory docstring) — repoint it explicitly at the patched
    (savepoint-based) factory so the function's internal session sees this test's writes.
    """
    monkeypatch.setattr(
        "src.bot.share_catalog_tip.async_session_factory", db_pkg.async_session_factory
    )
    trainer_id = await _create_pending_trainer_with_city(db_session)

    settings = MagicMock()
    settings.webapp_base_url = "https://example.com"
    settings.client_bot_username = "TestClientBot"
    monkeypatch.setattr("src.bot.share_catalog_tip.Settings", lambda: settings)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    await send_trainer_share_catalog_tip_to_chat(bot=bot, chat_id=12345, trainer_id=trainer_id)

    bot.send_message.assert_awaited_once()
    _, kwargs = bot.send_message.call_args
    assert kwargs["chat_id"] == 12345
    assert "start=client_" in kwargs["text"]
    assert "Следующий шаг к новым клиентам" in kwargs["text"]
