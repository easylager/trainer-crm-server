"""Regression: TrainerGateMiddleware does not invoke downstream handler when access is blocked.

We call ``_handle_message`` directly: ``__call__`` requires a real aiogram ``Message`` instance.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.trainer_access_state import TrainerAccessState
from src.bot.middlewares.trainer_gate_middleware import TrainerGateMiddleware
from src.bot.trainer_bot_state import trainer_booking_note_awaiting, trainer_support_awaiting


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
    trainer_booking_note_awaiting.discard(42)
    yield
    trainer_support_awaiting.discard(42)
    trainer_booking_note_awaiting.discard(42)


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


@pytest.mark.asyncio
async def test_gate_passes_callback_when_booking_ready(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, uid: int):
        return TrainerAccessState.BOOKING_READY, {"id": 1}

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    cb = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="booking_add_note:99",
        answer=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=42), id=1),
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )

    out = await mw._handle_callback(handler, cb, {})
    assert out == "ok"
    handler.assert_awaited_once()
    cb.answer.assert_not_called()


@pytest.mark.asyncio
async def test_gate_passes_booking_crm_callbacks_without_access_check(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state_should_not_run(_session, _uid: int):
        raise AssertionError("booking_add_note must bypass trainer access lookup")

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state_should_not_run,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    cb = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        data="booking_invite_client:77",
        answer=AsyncMock(),
        message=SimpleNamespace(chat=SimpleNamespace(id=42), id=1),
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
    )

    out = await mw._handle_callback(handler, cb, {})
    assert out == "ok"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_passes_booking_note_reply_while_blocked(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    trainer_booking_note_awaiting.add(42)

    async def fake_state(_session, uid: int):
        return TrainerAccessState.BLOCKED_PROFILE, None

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="saved")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="Заметка про клиента",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out == "saved"
    handler.assert_awaited_once_with(msg, {})
