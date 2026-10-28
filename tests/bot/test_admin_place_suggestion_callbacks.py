"""PDEC-028 Task 12: «Одобрить как есть» (psa:<id>) и /suggestions в админ-боте."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.application import place_suggestion_use_cases as uc
from src.bot.admin_bot_commands import ADMIN_BOT_COMMANDS
from src.bot.handlers import admin_handlers

BASE = "https://glide.example"
ADMIN = 4_242_000_001


async def _noop(*_a, **_kw):
    return None


@pytest.fixture(autouse=True)
def _env(monkeypatch, _test_db_core):
    """Никаких реальных сообщений в Telegram: .env держит боевые токены ботов."""
    monkeypatch.setattr(uc, "notify_admins_new_place_suggestion", _noop)
    monkeypatch.setattr(uc, "notify_author_approved", _noop)
    monkeypatch.setattr(admin_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(
        admin_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url=BASE, admin_telegram_ids=[ADMIN])
    )


async def _suggest(db_session, *, active_city=True, name="Каток-psa") -> int:
    r = await db_session.execute(
        text("INSERT INTO cities (name, sort_order, is_active, country) VALUES (:n, 9999, :a, 'BY') RETURNING id"),
        {"n": f"Пса-Бот-{uuid.uuid4().hex[:6]}", "a": active_city},
    )
    res = await uc.create_place_suggestion(
        db_session, source="site", kind="ice", city_id=int(r.scalar_one()), new_city=None, name=name,
        address=None, details={}, contact=None, author_telegram_id=None, client_ip=None,
    )
    return int(res["id"])


def _callback(data: str, user_id: int = ADMIN) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id)
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_approve_as_is_publishes_and_drops_buttons(db_session):
    sid = await _suggest(db_session)
    cb = _callback(f"psa:{sid}")
    await admin_handlers.on_place_suggestion_approve(cb)

    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    reply = cb.message.answer.await_args.args[0]
    assert reply.startswith(f"Опубликовано: {BASE}/")
    row = (await db_session.execute(
        text("SELECT status, result_arena_id FROM place_suggestions WHERE id=:id"), {"id": sid}
    )).one()
    assert row[0] == "approved" and row[1] is not None
    confirmed_by = (await db_session.execute(
        text("SELECT confirmed_by_admin_id FROM arenas WHERE id=:a"), {"a": row[1]}
    )).scalar()
    assert int(confirmed_by) == ADMIN

    again = _callback(f"psa:{sid}")
    await admin_handlers.on_place_suggestion_approve(again)
    again.answer.assert_awaited_once_with("Заявка уже разобрана", show_alert=True)
    again.message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_in_hidden_city_says_why_not_visible(db_session):
    sid = await _suggest(db_session, active_city=False)
    cb = _callback(f"psa:{sid}")
    await admin_handlers.on_place_suggestion_approve(cb)
    reply = cb.message.answer.await_args.args[0]
    assert reply.startswith(f"Заявка №{sid} одобрена, но место пока не видно в каталоге: город скрыт")


@pytest.mark.asyncio
async def test_non_admin_cannot_approve(db_session):
    sid = await _suggest(db_session)
    cb = _callback(f"psa:{sid}", user_id=1)
    await admin_handlers.on_place_suggestion_approve(cb)
    cb.answer.assert_awaited_once_with("Нет доступа", show_alert=True)
    status = (await db_session.execute(text("SELECT status FROM place_suggestions WHERE id=:id"), {"id": sid})).scalar()
    assert status == "new"


def test_approved_text_lists_every_reason():
    out = admin_handlers.format_place_suggestion_approved(
        7, {"url": "/p/x", "published": False, "city_kept_inactive": False, "country_not_public": True},
        base_url=BASE + "/",
    )
    assert out == (
        "Заявка №7 одобрена, но место пока не видно в каталоге: карточка — черновик, страна вне каталога.\n"
        f"{BASE}/p/x"
    )


@pytest.mark.asyncio
async def test_suggestions_command_counts_new_and_opens_webapp(db_session):
    await _suggest(db_session)
    async with admin_handlers.async_session_factory() as s:
        expected = await uc.count_new_place_suggestions(s)
    message = MagicMock()
    message.from_user = MagicMock(id=ADMIN)
    message.answer = AsyncMock()
    await admin_handlers.cmd_suggestions(message)
    body = message.answer.await_args.args[0]
    assert body.endswith(f"Новых заявок: {expected}") and expected >= 1
    button = message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.web_app.url == f"{BASE}/webapp/admin-place-suggestions"
    assert "suggestions" in [c.command for c in ADMIN_BOT_COMMANDS]


@pytest.mark.asyncio
async def test_approve_unexpected_error_alerts_and_keeps_buttons(db_session, monkeypatch):
    async def _boom(*_a, **_kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(admin_handlers, "approve_place_suggestion", _boom)
    cb = _callback("psa:1")
    await admin_handlers.on_place_suggestion_approve(cb)
    cb.answer.assert_awaited_once_with("Не удалось одобрить, см. логи", show_alert=True)
    cb.message.edit_reply_markup.assert_not_awaited()
    cb.message.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_approve_with_inaccessible_message_answers_in_alert(db_session):
    sid = await _suggest(db_session)
    cb = _callback(f"psa:{sid}")
    cb.message = None
    await admin_handlers.on_place_suggestion_approve(cb)
    text_arg = cb.answer.await_args.args[0]
    assert text_arg.startswith(f"Опубликовано: {BASE}/") and len(text_arg) <= 200
    assert cb.answer.await_args.kwargs == {"show_alert": True}

    again = _callback(f"psa:{sid}")
    again.message = None
    await admin_handlers.on_place_suggestion_approve(again)  # закрытая + нет сообщения — без падения
    again.answer.assert_awaited_once_with("Заявка уже разобрана", show_alert=True)
