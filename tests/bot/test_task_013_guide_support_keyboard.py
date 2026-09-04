"""TASK-013: help messages carry support inline keyboard; copy no longer points at /guide."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.application.trainer_access_state import TrainerAccessState
from src.bot import messages as msg
from src.bot.middlewares.trainer_gate_middleware import TrainerGateMiddleware
from src.bot.trainer_bot_state import trainer_booking_note_awaiting, trainer_support_awaiting
from src.bot.trainer_guide_keyboard import (
    TRAINER_SUPPORT_CALLBACK,
    keyboard_has_support_button,
    trainer_guide_keyboard,
)


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
    trainer_support_awaiting.discard(42)
    trainer_booking_note_awaiting.discard(42)
    yield
    trainer_support_awaiting.discard(42)
    trainer_booking_note_awaiting.discard(42)


def test_guide_keyboard_includes_support_callback() -> None:
    kb = trainer_guide_keyboard()
    assert keyboard_has_support_button(kb)


@pytest.mark.parametrize(
    "text",
    [
        msg.TRAINER_START_WELCOME,
        msg.TRAINER_LINK_SUCCESS_ACTIVE,
        msg.TRAINER_LINK_TELEGRAM_CONFLICT,
        msg.TRAINER_AFTER_LINK_STEP_DEACTIVATED,
        msg.TRAINER_GATE_DEACTIVATED,
    ],
)
def test_help_copy_does_not_advertise_slash_guide(text: str) -> None:
    assert "/guide" not in text


@pytest.mark.asyncio
async def test_gate_deactivated_message_includes_support_keyboard(
    monkeypatch: pytest.MonkeyPatch, patch_trainer_gate_session
) -> None:
    async def fake_state(_session, uid: int):
        return TrainerAccessState.DEACTIVATED, {"id": 1}

    monkeypatch.setattr(
        "src.bot.middlewares.trainer_gate_middleware.get_trainer_access_state",
        fake_state,
        raising=True,
    )
    mw = TrainerGateMiddleware()
    handler = AsyncMock(return_value="handler_ran")
    msg_obj = SimpleNamespace(
        from_user=SimpleNamespace(id=42),
        text="/editor",
        answer=AsyncMock(),
    )

    out = await mw._handle_message(handler, msg_obj, {})
    assert out is None
    handler.assert_not_called()
    msg_obj.answer.assert_awaited_once()
    kwargs = msg_obj.answer.await_args.kwargs
    assert kwargs.get("reply_markup") is not None
    assert keyboard_has_support_button(kwargs["reply_markup"])
    assert TRAINER_SUPPORT_CALLBACK in str(kwargs["reply_markup"].model_dump())
