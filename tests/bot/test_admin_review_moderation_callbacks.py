"""Кнопки «Подтвердить» / «Отклонить» (rvm:ok|no:<id>) и /reviews в админ-боте."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.application.trainer_use_cases import add_trainer_rating
from src.bot.admin_bot_commands import ADMIN_BOT_COMMANDS
from src.bot.handlers import admin_handlers

ADMIN = 4_242_000_002


@pytest.fixture(autouse=True)
def _env(monkeypatch, _test_db_core):
    monkeypatch.setattr(admin_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(
        admin_handlers, "Settings", lambda: SimpleNamespace(webapp_base_url="https://glide.example", admin_telegram_ids=[ADMIN])
    )


async def _pending_review(db_session) -> int:
    tid = int((await db_session.execute(text("SELECT id FROM trainers ORDER BY id LIMIT 1"))).scalar() or 0)
    if not tid:
        pytest.skip("нужен тренер в тестовой БД")
    tg = 7_000_000_000 + int((await db_session.execute(text("SELECT COALESCE(MAX(id),0)+1 FROM trainer_ratings"))).scalar())
    await add_trainer_rating(db_session, tid, tg, 5, review_text="Отличные занятия, спасибо")
    return int((await db_session.execute(text("SELECT id FROM trainer_ratings WHERE client_telegram_id=:c"), {"c": tg})).scalar())


def _callback(data: str, user_id: int = ADMIN) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, username="boss", full_name="Boss")
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.html_text = "Отзыв на проверку"
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


def test_reviews_command_is_in_the_admin_menu():
    assert "reviews" in {c.command for c in ADMIN_BOT_COMMANDS}


@pytest.mark.asyncio
async def test_approve_publishes_and_marks_the_card(db_session):
    rid = await _pending_review(db_session)
    cb = _callback(f"rvm:ok:{rid}")
    await admin_handlers.on_review_moderation(cb)

    status = (await db_session.execute(text("SELECT review_status, reviewed_by FROM trainer_ratings WHERE id=:i"), {"i": rid})).one()
    assert status[0] == "approved" and status[1] == ADMIN
    edited = cb.message.edit_text.await_args.args[0]
    assert "Подтверждён" in edited and cb.message.edit_text.await_args.kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_reject_and_second_tap_is_reported_as_closed(db_session):
    rid = await _pending_review(db_session)
    await admin_handlers.on_review_moderation(_callback(f"rvm:no:{rid}"))
    assert (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar() == "rejected"

    again = _callback(f"rvm:ok:{rid}")
    await admin_handlers.on_review_moderation(again)
    assert again.answer.await_args.args[0] == "Отзыв уже разобран"
    assert (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar() == "rejected"


@pytest.mark.asyncio
async def test_non_admin_cannot_moderate(db_session):
    rid = await _pending_review(db_session)
    cb = _callback(f"rvm:ok:{rid}", user_id=1)
    await admin_handlers.on_review_moderation(cb)
    assert cb.answer.await_args.args[0] == "Нет доступа"
    assert (await db_session.execute(text("SELECT review_status FROM trainer_ratings WHERE id=:i"), {"i": rid})).scalar() == "pending"
