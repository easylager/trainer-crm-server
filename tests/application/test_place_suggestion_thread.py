"""PDEC-028 Task 11: переписка с автором заявки и уведомление «место появилось»."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.enums import ChatType
from sqlalchemy import text

from src.application import place_suggestion_notify as notify
from src.application import place_suggestion_use_cases as uc
from src.application.place_suggestion_use_cases import (
    approve_place_suggestion,
    capture_author_reply,
    create_place_suggestion,
    send_message_to_author,
)
from src.bot import messages as msg
from src.bot.handlers import client_handlers

BASE = "https://glide.example"


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []

    async def _fake_send(**kw):
        calls.append(kw)

    monkeypatch.setattr(uc, "send_client_plain_notification", _fake_send)
    return calls


@pytest.fixture
def admin_replies(monkeypatch):
    calls: list[tuple[int, str]] = []

    async def _fake(sid, body):
        calls.append((sid, body))

    monkeypatch.setattr(uc, "notify_admins_place_suggestion_reply", _fake)
    return calls


def _tid() -> int:
    return 7_600_000_000 + (uuid.uuid4().int % 100_000_000)


async def _city(db_session, *, active=True, country="BY") -> int:
    r = await db_session.execute(
        text("INSERT INTO cities (name, sort_order, is_active, country) VALUES (:n, 9999, :a, :c) RETURNING id"),
        {"n": f"Пса-Тред-{uuid.uuid4().hex[:6]}", "a": active, "c": country},
    )
    return int(r.scalar_one())


async def _suggest(db_session, *, author, city_id=None, name="Каток-тред") -> int:
    res = await create_place_suggestion(
        db_session, source="miniapp", kind="ice", city_id=city_id,
        new_city=None if city_id else {"name": f"Пса-Тред-{uuid.uuid4().hex[:6]}", "country": "BY"},
        name=name, address=None, details={}, contact=None, author_telegram_id=author, client_ip=None,
    )
    return int(res["id"])


async def _messages(db_session, sid: int) -> list[tuple[str, str]]:
    r = await db_session.execute(
        text("SELECT direction, body FROM place_suggestion_messages WHERE suggestion_id=:id ORDER BY id"),
        {"id": sid},
    )
    return [tuple(x) for x in r.all()]


@pytest.mark.asyncio
async def test_send_writes_to_author_and_sets_needs_info(db_session, sent):
    tid = _tid()
    sid = await _suggest(db_session, author=tid, name="Каток <Юг>")
    res = await send_message_to_author(db_session, sid, "Какие часы работы?")
    assert res["delivered"] is True
    assert sent == [{
        "telegram_chat_id": tid,
        "html_text": f"Glide · заявка №{sid} «Каток &lt;Юг&gt;»\n\nКакие часы работы?\n\nОтветьте прямо здесь.",
    }]
    assert await _messages(db_session, sid) == [("to_author", "Какие часы работы?")]
    status = (await db_session.execute(text("SELECT status FROM place_suggestions WHERE id=:id"), {"id": sid})).scalar()
    assert status == "needs_info"


@pytest.mark.asyncio
async def test_reply_goes_to_the_asked_suggestion(db_session, sent, admin_replies):
    tid = _tid()
    asked = await _suggest(db_session, author=tid, name="Спросили")
    untouched = await _suggest(db_session, author=tid, name="Не спрашивали")
    await send_message_to_author(db_session, asked, "Есть прокат?")

    assert await capture_author_reply(db_session, tid, "  Да, есть  ") == asked
    assert await _messages(db_session, asked) == [("to_author", "Есть прокат?"), ("from_author", "Да, есть")]
    assert await _messages(db_session, untouched) == []
    assert admin_replies == [(asked, "Да, есть")]
    # Чужой Telegram — не наш автор.
    assert await capture_author_reply(db_session, _tid(), "Привет") is None


@pytest.mark.asyncio
async def test_reply_older_than_14_days_goes_to_support(db_session, sent, admin_replies):
    tid = _tid()
    sid = await _suggest(db_session, author=tid)
    await send_message_to_author(db_session, sid, "Адрес точный?")
    await db_session.execute(
        text("UPDATE place_suggestion_messages SET created_at = now() - interval '15 days' WHERE suggestion_id=:id"),
        {"id": sid},
    )
    await db_session.commit()
    assert await capture_author_reply(db_session, tid, "Да") is None
    assert admin_replies == []


@pytest.mark.asyncio
async def test_reply_without_question_is_not_captured(db_session, monkeypatch, admin_replies):
    async def _fail(**_kw):
        raise RuntimeError("blocked")

    monkeypatch.setattr(uc, "send_client_plain_notification", _fail)
    tid = _tid()
    sid = await _suggest(db_session, author=tid)
    res = await send_message_to_author(db_session, sid, "Вопрос")  # не доставлено → note
    assert res["delivered"] is False
    assert await capture_author_reply(db_session, tid, "Ответ") is None


def test_reply_notice_text_and_button():
    assert notify.format_place_suggestion_reply(12, "a <b>") == "Ответ по заявке №12: a &lt;b&gt;"
    kb = notify.place_suggestion_keyboard(12, base_url=BASE, can_approve=False)
    assert [b.text for b in kb.inline_keyboard[0]] == ["Открыть"]


@pytest.mark.asyncio
async def test_notify_author_approved_sends_link(db_session, sent, monkeypatch, _test_db_core):
    monkeypatch.setattr(uc, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(uc, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE + "/"))
    tid = _tid()
    city_id = await _city(db_session)
    sid = await _suggest(db_session, author=tid, city_id=city_id, name="Арена <Восток>")
    res = await approve_place_suggestion(db_session, sid, admin_id=1)
    assert res["published"] is True
    assert sent == [{
        "telegram_chat_id": tid,
        "html_text": f"Ваше место «Арена &lt;Восток&gt;» появилось в Glide: {BASE}{res['url']}",
    }]


@pytest.mark.asyncio
async def test_notify_author_approved_silent_without_author_or_hidden_city(
    db_session, sent, monkeypatch, _test_db_core
):
    monkeypatch.setattr(uc, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(uc, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE))
    site = await create_place_suggestion(
        db_session, source="site", kind="ice", city_id=await _city(db_session), new_city=None,
        name="Без автора", address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
    )
    await approve_place_suggestion(db_session, int(site["id"]), admin_id=1)
    hidden = await _suggest(db_session, author=_tid(), city_id=await _city(db_session, active=False))
    res = await approve_place_suggestion(db_session, hidden, admin_id=1)
    assert res["city_kept_inactive"] is True
    assert sent == []


def _private_text(tid: int, body: str) -> MagicMock:
    message = MagicMock()
    message.text = body
    message.from_user = MagicMock(id=tid)
    message.chat = SimpleNamespace(type=ChatType.PRIVATE)
    message.answer = AsyncMock()
    return message


@pytest.mark.asyncio
async def test_fallback_captures_reply_before_support(monkeypatch):
    monkeypatch.setattr(client_handlers, "maybe_route_client_relay_text_reply", AsyncMock(return_value=False))
    capture = AsyncMock(return_value=41)
    monkeypatch.setattr(client_handlers, "capture_author_reply", capture)
    monkeypatch.setattr(client_handlers, "async_session_factory", MagicMock())
    support = AsyncMock()
    monkeypatch.setattr(client_handlers, "create_support_message", support)
    tid = _tid()

    m = _private_text(tid, "Работают до 22")
    await client_handlers.fallback(m)
    assert capture.await_args.args[1:] == (tid, "Работают до 22")
    m.answer.assert_awaited_once_with(msg.CLIENT_SUGGEST_REPLY_SENT)
    support.assert_not_awaited()

    # Нажата «Поддержка» — текст уходит туда, заявку не трогаем.
    capture.reset_mock()
    client_handlers._client_support_awaiting.add(tid)
    try:
        m2 = _private_text(tid, "Не работает оплата")
        await client_handlers.fallback(m2)
    finally:
        client_handlers._client_support_awaiting.discard(tid)
    capture.assert_not_awaited()
    support.assert_awaited_once()
