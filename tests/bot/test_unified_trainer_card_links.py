"""TASK-407: под флагом бот ведёт на единую карточку и говорит текстом SPEC §8.2.

Флаг выключен — прежние адреса и прежние тексты.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.place_links import trainer_start_param
from src.bot import messages as msg
from src.bot.handlers import client_handlers as ch
from src.bot.start_entry import start_entry_reply
from src.shared.catalog_entry import client_discovery_webapp_url


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
        "pending": AsyncMock(),
    }
    monkeypatch.setattr(ch, "_bind_client_invite_trainer_context", state["bind"])
    monkeypatch.setattr(ch, "client_invite_needs_registration_form", state["needs_reg"])
    monkeypatch.setattr(ch, "get_trainer", AsyncMock(side_effect=lambda *_a, **_k: state["trainer"]))
    monkeypatch.setattr(ch, "record_profile_view_commit", AsyncMock())
    monkeypatch.setattr(ch, "get_or_create_client", AsyncMock(return_value=5))
    monkeypatch.setattr(ch, "default_profile_for_account", AsyncMock(return_value=None))
    monkeypatch.setattr(ch, "set_pending_referral", state["pending"])
    monkeypatch.setattr(ch, "count_trainer_services", AsyncMock(return_value=1))
    return state


def test_flag_off_start_param_still_opens_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    reply = start_entry_reply("trainer_7_s_55_v_p3", webapp_base_url="https://glide.example")
    assert reply is not None
    assert reply["url"] == "https://glide.example/webapp/client-home?startapp=trainer_7_s_55_v_p3"
    assert client_discovery_webapp_url("https://glide.example", trainer_id=12) == (
        "https://glide.example/webapp/catalog?trainer_id=12"
    )
    assert client_discovery_webapp_url(
        "https://glide.example", trainer_id=12, city_id=2, service_id=3, arena_id=9
    ) == "https://glide.example/webapp/catalog?trainer_id=12&city_id=2&service_id=3&arena_id=9"


def test_flag_on_start_param_opens_card_from_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    param = trainer_start_param(7, slot_id=55, via="p3")
    reply = start_entry_reply(param, webapp_base_url="https://glide.example/")
    assert reply is not None
    assert reply["url"] == "https://glide.example/webapp/trainers?trainer_id=7&slot_id=55&via=p3"
    assert start_entry_reply("welcome_ref_7", webapp_base_url="https://glide.example") is None
    assert client_discovery_webapp_url(
        "https://glide.example", trainer_id=12, city_id=2, service_id=4, arena_id=9
    ) == "https://glide.example/webapp/trainers?trainer_id=12&arena_id=9&service_id=4&city_id=2"


def test_flag_on_bot_keyboards_use_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    fill = msg.build_client_fill_slots_invite_keyboard(
        webapp_base_url="https://glide.example", trainer_id=7, online_booking=True, slot_id=55
    )
    assert fill.inline_keyboard[0][0].web_app.url == (
        "https://glide.example/webapp/trainers?trainer_id=7&slot_id=55"
    )
    catalog_fill = msg.build_client_fill_slots_invite_keyboard(
        webapp_base_url="https://glide.example", trainer_id=7, online_booking=False
    )
    assert catalog_fill.inline_keyboard[0][0].web_app.url == "https://glide.example/webapp/trainers?trainer_id=7"
    done = msg.build_client_booking_completed_inline_keyboard(
        webapp_base_url="https://glide.example",
        trainer_id=7,
        booking_id=1,
        trainer_telegram_id=None,
        show_repeat_row=False,
    )
    urls = [b.web_app.url for row in done.inline_keyboard for b in row if b.web_app]
    assert urls == ["https://glide.example/webapp/trainers?trainer_id=7"]
    again = msg.build_client_rebook_catalog_keyboard(webapp_base_url="https://glide.example", trainer_id=7)
    assert again.inline_keyboard[0][0].web_app.url == "https://glide.example/webapp/trainers?trainer_id=7"


def test_flag_off_bot_keyboards_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    fill = msg.build_client_fill_slots_invite_keyboard(
        webapp_base_url="https://glide.example", trainer_id=7, online_booking=True, slot_id=55
    )
    assert fill.inline_keyboard[0][0].web_app.url == "https://glide.example/webapp/book?trainer_id=7&slot_id=55"
    done = msg.build_client_booking_completed_inline_keyboard(
        webapp_base_url="https://glide.example",
        trainer_id=7,
        booking_id=1,
        trainer_telegram_id=None,
        show_repeat_row=False,
    )
    urls = [b.web_app.url for row in done.inline_keyboard for b in row if b.web_app]
    assert urls == ["https://glide.example/webapp/catalog?trainer_id=7"]


@pytest.mark.asyncio
async def test_new_client_copy_and_phone_step(wired, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    wired["needs_reg"].return_value = True
    message = _message("welcome_ref_7_s_55")
    await ch.cmd_start(message)
    wired["pending"].assert_awaited()
    wired["bind"].assert_not_awaited()
    text = message.answer.await_args.args[0]
    assert text == msg.unified_invite_new_client_html("Анна")
    assert "слева внизу" not in text
    assert "каталог" not in text.lower()
    buttons = _buttons(message)
    assert buttons[0].text == "Продолжить"
    assert _urls(message) == ["https://glide.example/webapp/client-register?trainer_id=7&via=link&slot_id=55"]


@pytest.mark.asyncio
async def test_registered_client_opens_the_card(wired, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    message = _message("welcome_ref_7_s_55")
    await ch.cmd_start(message)
    wired["bind"].assert_awaited_once()
    text = message.answer.await_args.args[0]
    assert "привязаны" in text
    assert "слева внизу" not in text
    buttons = _buttons(message)
    assert [b.text for b in buttons] == ["Открыть выбранное время", "Открыть карточку Анна"]
    assert _urls(message) == [
        "https://glide.example/webapp/trainers?trainer_id=7&slot_id=55&via=link",
        "https://glide.example/webapp/trainers?trainer_id=7&via=link",
    ]


@pytest.mark.asyncio
async def test_flag_off_registered_client_still_goes_home(wired, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIFIED_TRAINER_CARD_ENABLED", raising=False)
    message = _message("welcome_ref_7")
    await ch.cmd_start(message)
    text = message.answer.await_args.args[0]
    assert "слева внизу" in text
    assert _urls(message) == ["https://glide.example/webapp/client-home?via=link"]
    assert _buttons(message)[0].text == msg.CLIENT_BUTTON_TRAINER_AND_BOOKING


@pytest.mark.asyncio
async def test_unlisted_trainer_keeps_the_hub(wired, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIFIED_TRAINER_CARD_ENABLED", "true")
    wired["trainer"]["catalog_state"] = "draft"
    message = _message("welcome_ref_7_s_55")
    await ch.cmd_start(message)
    wired["bind"].assert_awaited_once()
    assert "слева внизу" in message.answer.await_args.args[0]
    assert _urls(message) == ["https://glide.example/webapp/client-home?via=link"]
