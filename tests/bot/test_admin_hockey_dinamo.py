"""Админ-поток правки итога Динамо: карточка проверки, подтверждение для разосланного итога, сообщение об
автоматическом итоге с удержанием рассылки."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import KIND_FINAL, Decision, apply_decision, get_match
from src.application.hockey_notices import SENT, deliver, due_notices
from src.application.hockey_review import (
    fix_result,
    hold_delivery,
    notify_auto_finals,
    notify_new_reviews,
    review_buttons,
    review_queue,
    review_text,
)
from src.bot.handlers import admin_handlers
from src.ingestion.hockey_sources import MINSK_TZ

ADMIN = 4_242_000_012
A, B = 9390001, 9390002


def at(hour: int, minute: int = 0, *, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MINSK_TZ)


@pytest.fixture(autouse=True)
def _env(monkeypatch, _test_db_core, db_session):
    monkeypatch.setattr(admin_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(
        admin_handlers,
        "Settings",
        lambda: SimpleNamespace(webapp_base_url="https://glide.example", admin_telegram_ids=[ADMIN]),
    )
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    admin_handlers._admin_awaiting_hockey_fix.clear()
    admin_handlers._admin_pending_hockey_fix.clear()


@pytest.fixture
def factory(db_session):
    @asynccontextmanager
    async def make():
        yield db_session

    return make


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def __call__(self, chat_id: int, body: str, buttons) -> str:
        self.sent.append((chat_id, body))
        return SENT


def _callback(data: str, user_id: int = ADMIN) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id)
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.html_text = "текст"
    return cb


def _message(body: str, user_id: int = ADMIN) -> MagicMock:
    m = MagicMock(spec=Message)
    m.text = body
    m.from_user = MagicMock(id=user_id)
    m.answer = AsyncMock()
    return m


async def _dinamo(db_session, mid: str = "d1") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Торпедо', :s) RETURNING id
                """),
            {"mid": mid, "s": at(17)},
        )
    ).scalar_one()


async def _picks(db_session, m: int) -> None:
    await make_pick(db_session, player_key=A, display_name="Саша", match_id=m, home_score=3, away_score=2, now=at(10))
    await make_pick(db_session, player_key=B, display_name="Катя", match_id=m, side="home", now=at(10))


async def _auto_final(db_session, m: int, when: datetime, home: int = 3, away: int = 2) -> None:
    """Итог, который записал автомат (apply_decision), с пояснением подтверждения в probe."""
    row = await get_match(db_session, m)
    await apply_decision(
        db_session, row, Decision(KIND_FINAL, home_score=home, away_score=away, decided_in="regulation"), now=when
    )
    await db_session.execute(
        text("UPDATE hockey_matches SET result_probe = CAST(:p AS jsonb) WHERE id = :i"),
        {"i": m, "p": json.dumps({"confirmed_by": "Источники: hcdinamo.by и hockey.by совпали (подтверждено двумя опросами)."})},
    )
    await score_finished_matches(db_session, now=when)


async def _status(db_session, m: int):
    return tuple(
        (await db_session.execute(text("SELECT status, home_score, away_score FROM hockey_matches WHERE id = :i"), {"i": m})).one()
    )


# --- B: карточка проверки Динамо ---


async def _review(db_session, probe: dict | None) -> int:
    m = await _dinamo(db_session, "rv")
    await db_session.execute(
        text("UPDATE hockey_matches SET status = 'review', review_reason = :r, result_probe = CAST(:p AS jsonb) WHERE id = :i"),
        {"i": m, "r": "итог менялся между опросами: был 3:2 (regulation), стал 4:2 (regulation)", "p": json.dumps(probe) if probe else None},
    )
    return m


@pytest.mark.asyncio
async def test_dinamo_review_card_explains_sources_and_offers_the_three_buttons(db_session, _test_db_core) -> None:
    probe = {
        "home": 4, "away": 2, "decided_in": "regulation", "conflict": True,
        "sources": "hcdinamo.by: 4:2\nhockey.by: 4:2, матч завершён\nsportmail.ru: таблица 4:2, страница: матч завершён",
    }
    m = await _review(db_session, probe)
    item = next(i for i in await review_queue(db_session) if i.id == m)
    body = review_text(item)
    assert "Динамо-Минск: итог на проверке" in body and "Почему не принят сам: итог менялся между опросами" in body
    assert "hockey.by: 4:2, матч завершён" in body and "Последнее чтение источников: 4:2, основное время" in body
    labels = [b["text"] for row in review_buttons(item) for b in row]
    assert labels == ["Принять 4:2 (основное время)", "Поправить", "Отменить матч"]

    sent: list[tuple[str, list]] = []

    async def send(b: str, buttons) -> bool:
        sent.append((b, buttons))
        return True

    assert await notify_new_reviews(_test_db_core["factory"], now=at(21), send=send) == 1
    assert await notify_new_reviews(_test_db_core["factory"], now=at(21), send=send) == 0

    cb = _callback(f"hk:ok:{m}")
    await admin_handlers.on_hockey_accept(cb)
    assert await _status(db_session, m) == ("final", 4, 2)
    assert "Итог принят: 4:2" in cb.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_dinamo_review_without_reading_offers_fix_and_cancel_only(db_session) -> None:
    m = await _review(db_session, None)
    item = next(i for i in await review_queue(db_session) if i.id == m)
    assert [b["text"] for row in review_buttons(item) for b in row] == ["Поправить", "Отменить матч"]


# --- B: подтверждение для уже разосланного итога ---


async def _delivered_final(db_session, factory) -> int:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))
    assert (await deliver(factory, now=at(21, 50), send=Outbox()))["sent"] == 2
    return m


@pytest.mark.asyncio
async def test_fixing_a_delivered_result_asks_once_then_notifies_players(db_session, factory) -> None:
    m = await _delivered_final(db_session, factory)
    await admin_handlers.on_hockey_fix(_callback(f"hk:fix:{m}"))
    msg = _message("2:3")
    await admin_handlers.on_admin_message(msg)
    ask = msg.answer.await_args
    assert ask.args[0] == "Итог уже разослан 2 игрокам. Им уйдёт сообщение с исправлением. Подтвердить?"
    assert [b.text for b in ask.kwargs["reply_markup"].inline_keyboard[0]] == ["Да", "Отмена"]
    assert await _status(db_session, m) == ("final", 3, 2)  # до «Да» ничего не записано

    yes = _callback(f"hk:fy:{m}")
    await admin_handlers.on_hockey_fix_confirm(yes)
    assert await _status(db_session, m) == ("final", 2, 3)
    assert yes.message.answer.await_args.args[0].endswith("Очки пересчитаны. Исправление уйдёт 2 игрокам.")


@pytest.mark.asyncio
async def test_declining_the_confirmation_changes_nothing(db_session, factory) -> None:
    m = await _delivered_final(db_session, factory)
    await admin_handlers.on_hockey_fix(_callback(f"hk:fix:{m}"))
    await admin_handlers.on_admin_message(_message("2:3"))
    no = _callback(f"hk:fn:{m}")
    await admin_handlers.on_hockey_fix_decline(no)
    assert await _status(db_session, m) == ("final", 3, 2)
    assert "Правка отменена" in no.message.answer.await_args.args[0]
    late = _callback(f"hk:fy:{m}")
    await admin_handlers.on_hockey_fix_confirm(late)  # старая кнопка «Да» уже не работает
    assert await _status(db_session, m) == ("final", 3, 2)


@pytest.mark.asyncio
async def test_fixing_a_not_yet_delivered_result_needs_no_confirmation(db_session) -> None:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))
    await admin_handlers.on_hockey_fix(_callback(f"hk:fix:{m}"))
    msg = _message("2:3 от")
    await admin_handlers.on_admin_message(msg)
    assert await _status(db_session, m) == ("final", 2, 3)
    assert msg.answer.await_args.args[0].startswith("Счёт записан:") and "Исправление уйдёт" not in msg.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_hockey_command_lists_dinamo_review_and_recent_results(db_session) -> None:
    await _review(db_session, {"home": 4, "away": 2, "decided_in": "regulation"})
    done = await _dinamo(db_session, "dn")
    await db_session.execute(
        text("""UPDATE hockey_matches SET status = 'final', home_score = 3, away_score = 1, decided_in = 'regulation',
                result_source = 'auto', finalized_at = now() WHERE id = :i"""),
        {"i": done},
    )
    msg = _message("/hockey")
    await admin_handlers._send_hockey_queue(msg)
    bodies = [c.args[0] for c in msg.answer.await_args_list]
    assert any("Динамо-Минск: итог на проверке" in b for b in bodies)
    recent = [c for c in msg.answer.await_args_list if c.args[0].startswith("<b>Недавний итог</b>")]
    assert recent and recent[0].kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"hk:fix:{done}"


# --- D: сообщение об автоматическом итоге и удержание рассылки ---


async def _notify(factory, when, send=None):
    out: list[tuple[str, list]] = []

    async def default(b: str, buttons) -> bool:
        out.append((b, buttons))
        return True

    return out, await notify_auto_finals(factory, now=when, send=send or default)


@pytest.mark.asyncio
async def test_auto_final_sends_one_admin_message_with_delivery_time(db_session, _test_db_core) -> None:
    m = await _dinamo(db_session)
    await _auto_final(db_session, m, at(21, 40))
    f = _test_db_core["factory"]
    out, n = await _notify(f, at(21, 41))
    assert n == 1 and len(out) == 1
    body, buttons = out[0]
    assert body == (
        "<b>Итог записан:</b> Динамо-Минск — Торпедо 3:2 (основное время).\n"
        "Источники: hcdinamo.by и hockey.by совпали (подтверждено двумя опросами).\n"
        "Клиентам уйдёт не раньше 21:45."
    )
    assert [(b["text"], b["callback_data"]) for b in buttons[0]] == [("Всё верно", f"hk:okd:{m}"), ("Поправить", f"hk:fix:{m}")]
    again, n2 = await _notify(f, at(21, 43))  # повторный тик не дублирует
    assert n2 == 0 and again == []


@pytest.mark.asyncio
async def test_auto_final_at_night_says_morning(db_session, _test_db_core) -> None:
    m = await _dinamo(db_session)
    await _auto_final(db_session, m, at(23, 30))
    out, _ = await _notify(_test_db_core["factory"], at(23, 31))
    assert out[0][0].endswith("Клиентам уйдёт утром в 09:00.")


@pytest.mark.asyncio
async def test_manual_result_gets_no_auto_message(db_session, _test_db_core) -> None:
    m = await _dinamo(db_session)
    await _auto_final(db_session, m, at(21, 40))
    await db_session.execute(text("UPDATE hockey_matches SET result_source = 'manual' WHERE id = :i"), {"i": m})
    out, n = await _notify(_test_db_core["factory"], at(21, 41))
    assert n == 0 and out == []


@pytest.mark.asyncio
async def test_all_correct_button_changes_nothing_and_delivery_goes_on(db_session, factory) -> None:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))
    cb = _callback(f"hk:okd:{m}")
    await admin_handlers.on_hockey_auto_ok(cb)
    cb.message.edit_text.assert_awaited_once()
    assert cb.message.edit_text.await_args.args[0].endswith("Подтверждено.")
    assert await _status(db_session, m) == ("final", 3, 2)
    assert (await deliver(factory, now=at(21, 46), send=Outbox()))["sent"] == 2


@pytest.mark.asyncio
async def test_fix_button_holds_delivery_and_the_corrected_result_goes_out_without_apology(db_session, factory) -> None:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))
    await hold_delivery(db_session, m, now=at(21, 42))
    out = Outbox()
    assert (await deliver(factory, now=at(21, 50), send=out))["sent"] == 0  # держим
    await fix_result(db_session, m, raw="2:3", now=at(21, 55))
    assert (await deliver(factory, now=at(21, 58), send=out))["sent"] == 0  # буфер от новой записи
    assert (await deliver(factory, now=at(22, 1), send=out))["sent"] == 2
    assert all("2:3" in body and not body.startswith("Мы ошиблись") for _, body in out.sent)
    assert [n.kind for n in await due_notices(db_session, now=at(22, 30))] == []  # исправление «ошиблись» не ставилось


@pytest.mark.asyncio
async def test_hold_expires_by_timeout_with_one_reminder(db_session, factory, _test_db_core) -> None:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))
    await hold_delivery(db_session, m, now=at(21, 42))
    assert (await deliver(factory, now=at(21, 50), send=Outbox()))["sent"] == 0  # удержание до 21:52
    assert (await deliver(factory, now=at(21, 53), send=Outbox()))["sent"] == 2  # 21:42 + 10 мин прошли
    f = _test_db_core["factory"]
    out, n = await _notify(f, at(21, 53))
    assert n == 2 and any(b.startswith("<b>Правка не завершена:</b>") for b, _ in out)
    again, n2 = await _notify(f, at(22, 0))
    assert n2 == 0 and again == []


@pytest.mark.asyncio
async def test_unreachable_admin_bot_does_not_block_the_game(db_session, factory, _test_db_core) -> None:
    m = await _dinamo(db_session)
    await _picks(db_session, m)
    await _auto_final(db_session, m, at(21, 40))

    async def down(b: str, buttons) -> bool:
        return False

    f = _test_db_core["factory"]
    _, n = await _notify(f, at(21, 41), send=down)
    assert n == 0
    assert (await deliver(factory, now=at(21, 46), send=Outbox()))["sent"] == 2  # клиенты получили итог по таймеру
    out, n2 = await _notify(f, at(21, 47))  # админ-бот вернулся: сообщение уходит на следующем тике, один раз
    assert n2 == 1 and len(out) == 1
    assert (await _notify(f, at(21, 49)))[1] == 0
