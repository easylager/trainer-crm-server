from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from src.bot.middlewares.service_unavailable_middleware import ServiceUnavailableMiddleware


def _event_and_bot() -> tuple[SimpleNamespace, SimpleNamespace]:
    event = SimpleNamespace(from_user=SimpleNamespace(id=42))
    bot = SimpleNamespace(send_message=AsyncMock())
    return event, bot


@pytest.mark.asyncio
async def test_middleware_answers_user_on_db_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAINTENANCE_MODE", "0")
    mw = ServiceUnavailableMiddleware()
    handler = AsyncMock(side_effect=OperationalError("SELECT 1", {}, Exception("connection refused")))
    event, bot = _event_and_bot()
    result = await mw(handler, event, {"bot": bot})
    assert result is None
    handler.assert_awaited()
    bot.send_message.assert_awaited()
    text = bot.send_message.await_args.args[1]
    assert "техническ" in text


@pytest.mark.asyncio
async def test_middleware_reraises_business_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAINTENANCE_MODE", "0")
    mw = ServiceUnavailableMiddleware()
    err = IntegrityError("INSERT", {}, Exception("duplicate key"))
    handler = AsyncMock(side_effect=err)
    event, bot = _event_and_bot()
    with pytest.raises(IntegrityError):
        await mw(handler, event, {"bot": bot})
    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_maintenance_mode_skips_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAINTENANCE_MODE", "1")
    mw = ServiceUnavailableMiddleware()
    handler = AsyncMock(return_value="ran")
    event, bot = _event_and_bot()
    result = await mw(handler, event, {"bot": bot})
    assert result is None
    handler.assert_not_called()
    bot.send_message.assert_awaited()
