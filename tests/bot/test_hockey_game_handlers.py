"""TASK-334 S6: ход и кнопки «Кто кого» в чате клиентского бота."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import text

from src.application.hockey_game import make_pick
from src.application.hockey_leagues import create_league, join_by_code
from src.bot.handlers import hockey_game_handlers as h

ME, OTHER = 9370001, 9370002


@pytest.fixture(autouse=True)
def _db(monkeypatch, _test_db_core):
    monkeypatch.setattr(h, "async_session_factory", _test_db_core["factory"])


def _callback(data: str, rows: list[list[tuple[str, str]]] | None = None, user_id: int = ME) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id, first_name="Саша", full_name="Саша К")
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.reply_markup = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=c) for t, c in row] for row in rows or []]
    )
    return cb


async def _match(db_session, starts_at: datetime, home="Юность", away="Шахтер") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES ('hockeyby', 'extraliga', replace(gen_random_uuid()::text, '-', ''), :home, :away, :starts_at) RETURNING id
                """),
            {"home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def _row(db_session, player=ME):
    return (
        await db_session.execute(
            text("SELECT side, home_score, away_score, doubled FROM hockey_picks WHERE player_key = :p"), {"p": player}
        )
    ).one_or_none()


@pytest.mark.asyncio
async def test_button_pick_is_saved_and_marks_the_chosen_side(db_session) -> None:
    m = await _match(db_session, datetime.now(timezone.utc) + timedelta(hours=2))
    rows = [[("Юность", f"kk:p:{m}:h"), ("Шахтер", f"kk:p:{m}:a")], [("Отключить такие сообщения", "kk:off:nm")]]
    cb = _callback(f"kk:p:{m}:a", rows)
    await h.on_pick(cb)
    assert tuple(await _row(db_session)) == ("away", None, None, False)
    cb.answer.assert_awaited_once_with("Ход принят: Шахтер")
    markup = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert [b.text for b in markup.inline_keyboard[0]] == ["Юность", "✓ Шахтер"]
    assert markup.inline_keyboard[1][0].callback_data == "kk:off:nm"
    # Сменить сторону до старта можно.
    await h.on_pick(_callback(f"kk:p:{m}:h", rows))
    assert (await _row(db_session)).side == "home"


@pytest.mark.asyncio
async def test_pick_after_start_says_closed_and_removes_buttons(db_session) -> None:
    m = await _match(db_session, datetime.now(timezone.utc) - timedelta(minutes=40))
    rows = [[("Юность", f"kk:p:{m}:h"), ("Шахтер", f"kk:p:{m}:a")], [("Отключить такие сообщения", "kk:off:nm")]]
    cb = _callback(f"kk:p:{m}:h", rows)
    await h.on_pick(cb)
    cb.answer.assert_awaited_once_with("Матч начался — ходы закрыты", show_alert=True)
    assert await _row(db_session) is None
    markup = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert [[b.callback_data for b in row] for row in markup.inline_keyboard] == [["kk:off:nm"]]


@pytest.mark.asyncio
async def test_garbage_and_missing_match_are_harmless(db_session) -> None:
    cb = _callback("kk:p:abc:h")
    await h.on_pick(cb)
    cb.answer.assert_awaited_once_with()
    gone = _callback("kk:p:99999999:h", [[("Юность", "kk:p:99999999:h")]])
    await h.on_pick(gone)
    assert gone.answer.await_args.args[0] == "Матча уже нет"


@pytest.mark.asyncio
async def test_next_move_sends_a_fresh_prompt_with_pick_buttons(db_session) -> None:
    nxt = await _match(db_session, datetime.now(timezone.utc) + timedelta(hours=5), home="Динамо-Минск", away="Трактор")
    cb = _callback("kk:n")
    await h.on_next(cb)
    cb.message.answer.assert_awaited_once()
    body = cb.message.answer.await_args.args[0]
    markup = cb.message.answer.await_args.kwargs["reply_markup"]
    assert "Твой ход?" in body
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert f"kk:p:{nxt}:h" in callbacks or any(c and c.startswith("kk:p:") for c in callbacks)


@pytest.mark.asyncio
async def test_off_button_disables_only_that_type(db_session) -> None:
    from src.application.hockey_notices import get_prefs

    cb = _callback("kk:off:nm", [[("Таблица", "x")], [("Отключить такие сообщения", "kk:off:nm")]])
    await h.on_off(cb)
    prefs = await get_prefs(db_session, ME)
    assert prefs["types"]["nomove"] is False and prefs["types"]["result"] is True
    markup = cb.message.edit_reply_markup.await_args.kwargs["reply_markup"]
    assert [[b.text for b in row] for row in markup.inline_keyboard] == [["Таблица"]]


@pytest.mark.asyncio
async def test_leave_button_leaves_the_extended_league(db_session) -> None:
    league = await create_league(db_session, owner_key=OTHER, owner_name="Катя", name="Офис")
    await join_by_code(db_session, player_key=ME, display_name="Саша", code=league.invite_code)
    cb = _callback(f"kk:lv:{league.id}", [[("Выйти из лиги", f"kk:lv:{league.id}")]])
    await h.on_leave(cb)
    assert cb.answer.await_args.args[0] == "Готово: ты вышел из лиги"
    left = (
        await db_session.execute(
            text("SELECT 1 FROM hockey_league_members WHERE league_id = :l AND player_key = :p"),
            {"l": league.id, "p": ME},
        )
    ).first()
    assert left is None
    again = _callback(f"kk:lv:{league.id}")
    await h.on_leave(again)
    assert again.answer.await_args.args[0] == "Тебя уже нет в этой лиге"
