"""`/start welcome_ref_<id>_s_<slot>` и `share_ref_<id>_s_<slot>`: привязка как раньше + кнопка на выбранное время.

Старые `welcome_ref_<id>` / `share_ref_<id>` работают без изменений (кнопки со слотом нет).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers import client_handlers as ch


class _DummySessionFactory:
    def __call__(self) -> "_DummySessionFactory":
        return self

    async def __aenter__(self) -> MagicMock:
        return MagicMock(commit=AsyncMock())

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _message(payload: str) -> MagicMock:
    message = MagicMock()
    message.text = f"/start {payload}"
    message.from_user = MagicMock(id=1304982166, username="owner")
    message.answer = AsyncMock()
    return message


def _buttons(message: MagicMock) -> list:
    markup = message.answer.await_args.kwargs["reply_markup"]
    return [b for row in markup.inline_keyboard for b in row]


def _urls(message: MagicMock) -> list[str]:
    return [b.web_app.url for b in _buttons(message) if b.web_app]


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WEBAPP_BASE_URL", "https://glide.example")
    monkeypatch.setattr(ch, "async_session_factory", _DummySessionFactory())
    state = {
        "bind": AsyncMock(return_value=(1, None)),
        "needs_reg": AsyncMock(return_value=False),
        "trainer": {"id": 7, "catalog_state": "published", "profile": {"first_name": "Анна"}},
    }
    monkeypatch.setattr(ch, "_bind_client_invite_trainer_context", state["bind"])
    monkeypatch.setattr(ch, "client_invite_needs_registration_form", state["needs_reg"])
    monkeypatch.setattr(ch, "get_trainer", AsyncMock(side_effect=lambda *_a, **_k: state["trainer"]))
    monkeypatch.setattr(ch, "record_profile_view_commit", AsyncMock())
    monkeypatch.setattr(ch, "get_or_create_client", AsyncMock(return_value=5))
    monkeypatch.setattr(ch, "default_profile_for_account", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "set_pending_referral", AsyncMock())
    monkeypatch.setattr(ch, "count_trainer_services", AsyncMock(return_value=1))
    return state


def test_parsers_keep_old_format_and_read_slot_tail() -> None:
    assert ch._parse_welcome_ref("welcome_ref_7") == 7
    assert ch._parse_share_ref("share_ref_7") == 7
    assert ch._parse_ref_with_slot("welcome_ref_7", "welcome_ref_", ch._parse_welcome_ref) == (7, None)
    assert ch._parse_ref_with_slot("welcome_ref_7_s_55", "welcome_ref_", ch._parse_welcome_ref) == (7, 55)
    assert ch._parse_ref_with_slot("share_ref_7_s_55", "share_ref_", ch._parse_share_ref) == (7, 55)
    # Кривой хвост — не ссылка (как раньше любой нечисловой хвост).
    assert ch._parse_ref_with_slot("welcome_ref_7_s_", "welcome_ref_", ch._parse_welcome_ref) is None
    assert ch._parse_ref_with_slot("welcome_ref_7_s_0", "welcome_ref_", ch._parse_welcome_ref) is None
    assert ch._parse_ref_with_slot("welcome_ref_7_x_5", "welcome_ref_", ch._parse_welcome_ref) is None
    assert ch._parse_ref_with_slot("share_ref_7_s_5", "welcome_ref_", ch._parse_welcome_ref) is None


@pytest.mark.asyncio
async def test_welcome_ref_with_slot_binds_and_adds_slot_button(wired) -> None:
    message = _message("welcome_ref_7_s_55")
    await ch.cmd_start(message)
    wired["bind"].assert_awaited_once()
    assert wired["bind"].await_args.args[1] == 7
    urls = _urls(message)
    assert "https://glide.example/webapp/trainers?trainer_id=7&slot_id=55&via=link" in urls
    assert "https://glide.example/webapp/client-home?via=link" in urls


@pytest.mark.asyncio
async def test_welcome_ref_without_slot_is_unchanged(wired) -> None:
    message = _message("welcome_ref_7")
    await ch.cmd_start(message)
    wired["bind"].assert_awaited_once()
    assert _urls(message) == ["https://glide.example/webapp/client-home?via=link"]


@pytest.mark.asyncio
async def test_welcome_ref_with_slot_unlisted_trainer_has_no_slot_button(wired) -> None:
    wired["trainer"]["catalog_state"] = "draft"
    message = _message("welcome_ref_7_s_55")
    await ch.cmd_start(message)
    wired["bind"].assert_awaited_once()
    assert _urls(message) == ["https://glide.example/webapp/client-home?via=link"]


@pytest.mark.asyncio
async def test_welcome_ref_registration_branch_carries_slot(wired) -> None:
    wired["needs_reg"].return_value = True
    with_slot = _message("welcome_ref_7_s_55")
    await ch.cmd_start(with_slot)
    assert _urls(with_slot) == ["https://glide.example/webapp/client-register?trainer_id=7&via=link&slot_id=55"]
    wired["bind"].assert_not_awaited()
    plain = _message("welcome_ref_7")
    await ch.cmd_start(plain)
    assert _urls(plain) == ["https://glide.example/webapp/client-register?trainer_id=7&via=link"]


@pytest.mark.asyncio
async def test_share_ref_with_slot_adds_slot_button_before_card(wired) -> None:
    message = _message("share_ref_7_s_55")
    await ch.cmd_start(message)
    urls = _urls(message)
    assert urls[0] == "https://glide.example/webapp/trainers?trainer_id=7&slot_id=55&via=share"
    assert any("/webapp/catalog?trainer_id=7" in u for u in urls[1:])
    plain = _message("share_ref_7")
    await ch.cmd_start(plain)
    assert not any("/webapp/trainers" in u for u in _urls(plain))
    assert any("/webapp/catalog?trainer_id=7" in u for u in _urls(plain))
