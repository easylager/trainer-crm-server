"""Regression: TrainerGateMiddleware only blocks NOT_LINKED and DEACTIVATED.

Onboarding v2 removed the profile-completeness tiers, so a linked trainer with an empty
profile passes straight through — see tests/application/test_trainer_access_state.py.

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
async def test_gate_blocks_handler_when_deactivated(monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session) -> None:
    seen: list[int] = []

    async def fake_state(_session, uid: int):
        seen.append(uid)
        return TrainerAccessState.DEACTIVATED, None

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
async def test_gate_passes_allowlisted_command_when_deactivated(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, _uid: int):
        return TrainerAccessState.DEACTIVATED, {"id": 1}

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
async def test_gate_passes_allowlisted_home_when_deactivated(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, _uid: int):
        return TrainerAccessState.DEACTIVATED, {"id": 1}

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/home",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out == "ok"
    handler.assert_awaited_once_with(msg, {})


@pytest.mark.asyncio
async def test_gate_blocks_allowlisted_command_when_not_linked(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, uid: int):
        return TrainerAccessState.NOT_LINKED, None

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/home",
        chat=SimpleNamespace(id=99),
        bot=SimpleNamespace(send_chat_action=AsyncMock()),
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out is None
    handler.assert_not_called()
    msg.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_gate_passes_welcome_link_start_when_not_linked(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, uid: int):
        return TrainerAccessState.NOT_LINKED, None

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="linked")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/start link_secret_token",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out == "linked"
    handler.assert_awaited_once_with(msg, {})
    msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_gate_passes_booking_callback_for_active_trainer(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, uid: int):
        return TrainerAccessState.ACTIVE, {"id": 1}

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
async def test_gate_passes_booking_crm_callbacks_for_linked_trainer(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, _uid: int):
        return TrainerAccessState.ACTIVE, {"id": 1}

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
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
async def test_gate_passes_booking_note_reply_while_deactivated(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    trainer_booking_note_awaiting.add(42)

    async def fake_state(_session, uid: int):
        return TrainerAccessState.DEACTIVATED, None

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


@pytest.mark.asyncio
async def test_gate_passes_new_trainer_with_empty_profile(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    """
    The onboarding v2 promise: a trainer linked one second ago, with nothing filled in,
    reaches every handler. Previously this hit BLOCKED_PROFILE and got a wall of text.
    """

    async def fake_state(_session, _uid: int):
        return TrainerAccessState.ACTIVE, {"id": 1, "status": "pending_profile", "profile": {}}

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="ok")

    msg = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="какой-то произвольный текст",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg, {})
    assert out == "ok"
    handler.assert_awaited_once_with(msg, {})
    msg.answer.assert_not_called()
