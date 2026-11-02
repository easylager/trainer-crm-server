"""TASK-334 S6: админ-бот — очередь проверки итогов Экстралиги и кнопка «Закрыть месяц»."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import set_manual_result
from src.application.hockey_races import ensure_month_race, mark_calendar_synced, pending_month_closures
from src.application.hockey_review import (
    ReviewError,
    notify_new_reviews,
    parse_fix,
    review_buttons,
    review_queue,
    review_text,
)
from src.bot.handlers import admin_handlers
from src.ingestion.hockey_sources import MINSK_TZ

ADMIN = 4_242_000_011
A, B, C = 9380001, 9380002, 9380003


def at(day: int, hour: int = 19) -> datetime:
    return datetime(2026, 11, day, hour, 0, tzinfo=MINSK_TZ)


@pytest.fixture(autouse=True)
def _env(monkeypatch, _test_db_core):
    monkeypatch.setattr(admin_handlers, "async_session_factory", _test_db_core["factory"])
    monkeypatch.setattr(
        admin_handlers,
        "Settings",
        lambda: SimpleNamespace(webapp_base_url="https://glide.example", admin_telegram_ids=[ADMIN]),
    )
    admin_handlers._admin_awaiting_hockey_fix.clear()


def _callback(data: str, user_id: int = ADMIN) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=user_id)
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.answer = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    return cb


def _message(body: str, user_id: int = ADMIN) -> MagicMock:
    m = MagicMock(spec=Message)
    m.text = body
    m.from_user = MagicMock(id=user_id)
    m.answer = AsyncMock()
    return m


async def _review_match(db_session, mid: str, *, probe: dict | None, start=None, picks=()) -> int:
    """Матч на проверке. Ходы ставятся до этого, пока матч ещё «scheduled»: на проверке ходы уже закрыты."""
    m = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES ('hockeyby', 'extraliga', :mid, 'Юность', 'Неман', :starts_at) RETURNING id
                """),
            {"mid": mid, "starts_at": start or at(1, 19)},
        )
    ).scalar_one()
    for key, kwargs in picks:
        await make_pick(
            db_session, player_key=key, display_name="И", match_id=m, now=at(1, 10) - timedelta(days=5), **kwargs
        )
    await db_session.execute(
        text("""
            UPDATE hockey_matches SET status = 'review', review_reason = 'счёт менялся между опросами: был 2:1',
                   result_probe = CAST(:probe AS jsonb) WHERE id = :m
            """),
        {"m": m, "probe": json.dumps(probe) if probe else None},
    )
    return m


async def _state(db_session, match_id: int):
    return (
        await db_session.execute(
            text("SELECT status, home_score, away_score, decided_in FROM hockey_matches WHERE id = :i"), {"i": match_id}
        )
    ).one()


PROBE = {"home": 3, "away": 2, "decided_in": "ot", "first_seen_at": "2026-11-01T20:00:00+00:00"}


def test_parse_fix_accepts_regulation_overtime_shootout() -> None:
    assert parse_fix("3:2") == (3, 2, "regulation")
    assert parse_fix(" 4-3 ОТ ") == (4, 3, "ot")
    assert parse_fix("2:1 б") == (2, 1, "so")
    assert parse_fix("2:1 буллиты") == (2, 1, "so")
    for bad in ("", "три два", "3:2 вечность", "3"):
        with pytest.raises(ReviewError):
            parse_fix(bad)


@pytest.mark.asyncio
async def test_queue_card_offers_accept_only_with_a_full_probe(db_session) -> None:
    full = await _review_match(db_session, "q1", probe=PROBE)
    bare = await _review_match(db_session, "q2", probe={"home": 3, "away": 2, "decided_in": None})
    queue = {i.id: i for i in await review_queue(db_session)}
    assert queue[full].probe_ready and not queue[bare].probe_ready
    assert [b["text"] for b in review_buttons(queue[full])[0]] == ["Принять 3:2"]
    assert [b["text"] for row in review_buttons(queue[bare]) for b in row] == ["Поправить", "Отменить матч"]
    body = review_text(queue[full])
    assert "Юность — Неман" in body and "Последний опрос hockey.by: 3:2, овертайм" in body


@pytest.mark.asyncio
async def test_accept_closes_the_match_and_scores_picks(db_session) -> None:
    m = await _review_match(db_session, "a1", probe=PROBE, picks=[(A, {"side": "home"})])
    cb = _callback(f"hk:ok:{m}")
    await admin_handlers.on_hockey_accept(cb)
    assert tuple(await _state(db_session, m)) == ("final", 3, 2, "ot")
    points = (
        await db_session.execute(text("SELECT points FROM hockey_picks WHERE match_id = :m"), {"m": m})
    ).scalar_one()
    assert points == 20
    assert "Итог принят: 3:2 (овертайм)" in cb.answer.await_args.args[0]
    cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    # Повторное нажатие — понятный отказ, ничего не меняется.
    again = _callback(f"hk:ok:{m}")
    await admin_handlers.on_hockey_accept(again)
    assert again.answer.await_args.args[0] == "Матч уже не на проверке"


@pytest.mark.asyncio
async def test_accept_without_full_probe_is_refused(db_session) -> None:
    m = await _review_match(db_session, "a2", probe={"home": 3, "away": 2, "decided_in": None})
    cb = _callback(f"hk:ok:{m}")
    await admin_handlers.on_hockey_accept(cb)
    assert "поправьте счёт вручную" in cb.answer.await_args.args[0]
    assert (await _state(db_session, m)).status == "review"


@pytest.mark.asyncio
async def test_fix_flow_asks_for_the_score_then_closes_the_match(db_session) -> None:
    m = await _review_match(db_session, "f1", probe=None, picks=[(A, {"home_score": 4, "away_score": 1})])
    await admin_handlers.on_hockey_fix(_callback(f"hk:fix:{m}"))
    assert admin_handlers._admin_awaiting_hockey_fix[ADMIN] == m
    bad = _message("пятьдесят")
    await admin_handlers.on_admin_message(bad)
    assert "Формат: 3:2" in bad.answer.await_args.args[0]
    assert admin_handlers._admin_awaiting_hockey_fix[ADMIN] == m  # ждём дальше
    wrong_ot = _message("5:2 от")  # в овертайме разница ровно в шайбу
    await admin_handlers.on_admin_message(wrong_ot)
    assert (await _state(db_session, m)).status == "review"
    good = _message("4:1")
    await admin_handlers.on_admin_message(good)
    assert tuple(await _state(db_session, m)) == ("final", 4, 1, "regulation")
    assert "Счёт записан" in good.answer.await_args.args[0]
    assert ADMIN not in admin_handlers._admin_awaiting_hockey_fix
    points = (
        await db_session.execute(text("SELECT points FROM hockey_picks WHERE match_id = :m"), {"m": m})
    ).scalar_one()
    assert points == 50


@pytest.mark.asyncio
async def test_fix_can_be_cancelled(db_session) -> None:
    m = await _review_match(db_session, "f2", probe=None)
    await admin_handlers.on_hockey_fix(_callback(f"hk:fix:{m}"))
    msg = _message("/cancel")
    await admin_handlers.on_admin_message(msg)
    assert msg.answer.await_args.args[0] == "Ввод счёта отменён."
    assert (await _state(db_session, m)).status == "review"


@pytest.mark.asyncio
async def test_cancel_needs_a_second_tap_and_returns_the_trump(db_session) -> None:
    m = await _review_match(db_session, "c1", probe=PROBE, picks=[(A, {"side": "home"})])
    ask = _callback(f"hk:no:{m}")
    await admin_handlers.on_hockey_cancel_ask(ask)
    assert (await _state(db_session, m)).status == "review"
    assert ask.message.answer.await_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"hk:no2:{m}"
    await admin_handlers.on_hockey_cancel(_callback(f"hk:no2:{m}"))
    assert (await _state(db_session, m)).status == "cancelled"


@pytest.mark.asyncio
async def test_non_admin_cannot_press_anything(db_session) -> None:
    m = await _review_match(db_session, "n1", probe=PROBE)
    cb = _callback(f"hk:ok:{m}", user_id=777)
    await admin_handlers.on_hockey_accept(cb)
    cb.answer.assert_awaited_once_with("Нет доступа", show_alert=True)
    assert (await _state(db_session, m)).status == "review"


@pytest.mark.asyncio
async def test_new_review_gets_one_card_for_the_admin_bot(db_session, _test_db_core) -> None:
    m = await _review_match(db_session, "k1", probe=PROBE)
    sent: list[tuple[str, list]] = []

    async def send(body: str, buttons) -> bool:
        sent.append((body, buttons))
        return True

    assert await notify_new_reviews(_test_db_core["factory"], now=at(1, 23), send=send) >= 1
    assert any("Юность — Неман" in body for body, _ in sent)
    assert any(b["callback_data"] == f"hk:ok:{m}" for _, rows in sent for row in rows for b in row)
    before = len(sent)
    assert await notify_new_reviews(_test_db_core["factory"], now=at(1, 23), send=send) == 0
    assert len(sent) == before

    # Админ-бот недоступен — карточка не считается доставленной и уйдёт на следующем тике.
    m2 = await _review_match(db_session, "k2", probe=PROBE)

    async def down(body: str, buttons) -> bool:
        return False

    assert await notify_new_reviews(_test_db_core["factory"], now=at(1, 23), send=down) == 0
    assert await notify_new_reviews(_test_db_core["factory"], now=at(1, 23), send=send) == 1
    assert m2


async def _full_month(db_session) -> None:
    """Три игрока с очками в ноябре по Юности, всё сыграно 20-го."""
    await ensure_month_race(db_session, now=at(10))
    m1 = (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES ('hockeyby', 'extraliga', 'cm1', 'Юность', 'Неман', :s) RETURNING id
                """),
            {"s": at(20)},
        )
    ).scalar_one()
    for key, (hs, as_) in ((A, (3, 1)), (B, (2, 1)), (C, (1, 0))):
        await make_pick(
            db_session, player_key=key, display_name=f"И{key}", match_id=m1, home_score=hs, away_score=as_, now=at(19)
        )
    await set_manual_result(db_session, m1, home_score=3, away_score=1, decided_in="regulation", now=at(20, 22))
    await score_finished_matches(db_session, now=at(20, 22))
    await mark_calendar_synced(db_session, now=at(25))


@pytest.mark.asyncio
async def test_close_month_button_writes_crowns_once(db_session) -> None:
    await _full_month(db_session)
    pending = await pending_month_closures(db_session, now=at(26))
    assert {p["club"] for p in pending} >= {None, "Юность"}
    assert pending[0]["leaders"][0][1] == 50
    race_id = pending[0]["race_id"]

    cb = _callback(f"hk:cm:{race_id}:-")
    await admin_handlers.on_hockey_close_month(cb)
    assert cb.answer.await_args.args[0] == "Месяц закрыт: короны записаны."
    crowns = (
        await db_session.execute(
            text("SELECT player_key, club FROM hockey_crowns WHERE period_start = :s"), {"s": at(1, 0)}
        )
    ).all()
    assert [(c.player_key, c.club) for c in crowns] == [(A, None)]
    # Нажать второй раз — ничего не дублируется.
    again = _callback(f"hk:cm:{race_id}:-")
    await admin_handlers.on_hockey_close_month(again)
    assert again.answer.await_args.args[0] == "Этот срез уже закрыт."
    count = (await db_session.execute(text("SELECT COUNT(*) FROM hockey_crowns WHERE club IS NULL"))).scalar_one()
    assert count == 1
    # Срез клуба — отдельная кнопка со своим названием.
    club_cb = _callback(f"hk:cm:{race_id}:Юность")
    await admin_handlers.on_hockey_close_month(club_cb)
    assert club_cb.answer.await_args.args[0] == "Месяц закрыт: короны записаны."


@pytest.mark.asyncio
async def test_close_month_refuses_while_matches_are_open(db_session) -> None:
    race = await ensure_month_race(db_session, now=at(10))
    await db_session.execute(
        text("""
            INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
            VALUES ('hockeyby', 'extraliga', 'cm9', 'Юность', 'Неман', :s)
            """),
        {"s": at(28)},
    )
    cb = _callback(f"hk:cm:{race.id}:-")
    await admin_handlers.on_hockey_close_month(cb)
    assert "несыгранные" in cb.answer.await_args.args[0] or "Срез закрыть нельзя" in cb.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_hockey_command_lists_queue_and_months(db_session) -> None:
    await _full_month(db_session)
    # Матч на проверке из октября: ноябрьский срез он не держит.
    m = await _review_match(db_session, "z1", probe=PROBE, start=datetime(2026, 10, 30, 19, 0, tzinfo=MINSK_TZ))
    msg = _message("/hockey")
    await admin_handlers._send_hockey_queue(msg)
    bodies = [c.args[0] for c in msg.answer.await_args_list]
    assert any("Экстралига: итог на проверке" in b for b in bodies)
    assert any(b.startswith("<b>Корона: ") for b in bodies)
    assert m
