"""Клиентский бот: короткий текст про катки — кнопка на главную Mini App, а не обращение в поддержку."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatType

from src.bot import messages as msg
from src.bot.handlers import client_handlers
from src.bot.rink_query import is_rink_query

CITIES = ("Минск", "Гродно", "Гомель", "Могилёв")
LONG_PROBLEM = "не могу оплатить абонемент, списались деньги дважды, помогите вернуть"


@pytest.mark.parametrize(
    "text",
    [
        "Минск Массовое Катание",
        "каток гродно",
        "хоккей",
        "Где лёд в Могилёве",
        "фигурное катание",
        "прокат коньков",
        "заточка",
        "расписание сеансов",
        "гомеле",
    ],
)
def test_search_like_text_matches(text: str) -> None:
    assert is_rink_query(text, CITIES)


@pytest.mark.parametrize("text", [LONG_PROBLEM, "не могу оплатить абонемент", "привет", "", "/start"])
def test_support_like_text_does_not_match(text: str) -> None:
    assert not is_rink_query(text, CITIES)


def test_long_text_about_rinks_stays_a_support_request() -> None:
    assert not is_rink_query("каток " + "очень длинное описание проблемы " * 4, CITIES)


def test_no_false_hit_inside_a_word() -> None:
    assert not is_rink_query("проблема с ПОЛЕДЕНЦОМ", ())


def _msg(tid: int, body: str) -> MagicMock:
    m = MagicMock()
    m.text = body
    m.from_user = MagicMock(id=tid)
    m.chat = SimpleNamespace(type=ChatType.PRIVATE)
    m.answer = AsyncMock()
    return m


@pytest.fixture
def wired(monkeypatch):
    monkeypatch.setattr(client_handlers, "maybe_route_client_relay_text_reply", AsyncMock(return_value=False))
    monkeypatch.setattr(client_handlers, "capture_author_reply", AsyncMock(return_value=None))
    monkeypatch.setattr(client_handlers, "async_session_factory", MagicMock())
    monkeypatch.setattr(client_handlers, "known_city_names", AsyncMock(return_value=CITIES))
    support = AsyncMock()
    monkeypatch.setattr(client_handlers, "create_support_message", support)
    client_handlers._client_support_awaiting.discard(9001)
    yield support
    client_handlers._client_support_awaiting.discard(9001)


def _has_home_button(m: MagicMock) -> bool:
    kb = m.answer.await_args.kwargs["reply_markup"]
    return len(kb.inline_keyboard) == 1 and len(kb.inline_keyboard[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["Минск Массовое Катание", "каток гродно", "хоккей"])
async def test_rink_text_gets_button_and_no_ticket(wired, body: str) -> None:
    m = _msg(9001, body)
    await client_handlers.fallback(m)
    wired.assert_not_awaited()
    assert m.answer.await_args.args == (msg.CLIENT_RINK_QUERY_REPLY,)
    assert _has_home_button(m)


@pytest.mark.asyncio
async def test_rink_text_in_support_mode_gets_button_and_clears_mode(wired) -> None:
    client_handlers._client_support_awaiting.add(9001)
    m = _msg(9001, "Минск Массовое Катание")
    await client_handlers.fallback(m)
    wired.assert_not_awaited()
    assert 9001 not in client_handlers._client_support_awaiting
    assert m.answer.await_args.args == (msg.CLIENT_RINK_QUERY_REPLY,)
    assert _has_home_button(m)


@pytest.mark.asyncio
async def test_real_problem_in_support_mode_creates_ticket(wired) -> None:
    client_handlers._client_support_awaiting.add(9001)
    m = _msg(9001, LONG_PROBLEM)
    await client_handlers.fallback(m)
    wired.assert_awaited_once()
    assert m.answer.await_args.args == (msg.CLIENT_SUPPORT_SENT,)


@pytest.mark.asyncio
async def test_unclear_text_fallback_has_home_button(wired) -> None:
    m = _msg(9001, "привет")
    await client_handlers.fallback(m)
    wired.assert_not_awaited()
    assert m.answer.await_args.args == (msg.CLIENT_FALLBACK,)
    assert _has_home_button(m)


def test_guide_first_button_opens_app_second_is_support() -> None:
    rows = client_handlers._guide_keyboard().inline_keyboard
    assert rows[0][0].text == msg.CLIENT_BUTTON_OPEN_RINKS
    assert rows[1][0].callback_data == client_handlers.CLIENT_SUPPORT_CALLBACK
