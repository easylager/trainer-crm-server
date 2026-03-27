"""Regression: TrainerGateMiddleware does not invoke downstream handler when access is blocked.

We call ``_handle_message`` directly: ``__call__`` requires a real aiogram ``Message`` instance.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.trainer_access_state import TrainerAccessState
from src.bot.middlewares.trainer_gate_middleware import TrainerGateMiddleware
from src.bot.trainer_bot_state import trainer_support_awaiting


class _FakeSessionCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return None


@pytest.fixture
def patch_trainer_gate_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.async_session_factory",
        lambda: _FakeSessionCM(),
    )


@pytest.fixture(autouse=True)
def _no_trainer_support_pollution() -> None:
    """Support flow bypasses DB; clear ids used in tests so middleware hits get_trainer_access_state."""
    trainer_support_awaiting.discard(42)
    yield
    trainer_support_awaiting.discard(42)


@pytest.mark.asyncio
async def test_gate_blocks_handler_when_not_active(monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session) -> None:
    seen: list[int] = []

    async def fake_state(_session, uid: int):
        seen.append(uid)
        return TrainerAccessState.BLOCKED_PROFILE, None

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="handler_ran")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/editor",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert seen == [42], "middleware must resolve access via patched get_trainer_access_state"
    assert out is None
    handler.assert_not_called()
    msg.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_passes_allowlisted_command_even_if_blocked(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, _uid: int):
        raise AssertionError("allowlisted commands must not hit DB access state")

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/myprofile",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out == "ok"
    handler.assert_awaited_once_with(msg, {})
    msg.answer.assert_not_called()
