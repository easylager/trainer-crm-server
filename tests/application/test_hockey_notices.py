"""TASK-334 S6: бот «Кто кого» — четыре повода, дневной бюджет, ход из чата, блокировка, «лига продлена»."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_leagues import build_terms, create_league, extend_league, join_by_code
from src.application.hockey_matches import set_manual_result
from src.application.hockey_notices import (
    BLOCKED,
    FAILED,
    SENT,
    chat_pick,
    deliver,
    deliver_league_notices,
    due_notices,
    get_prefs,
    in_quiet_hours,
    next_move,
    scan_league_ranks,
    set_fav_club,
    set_remind,
    set_type,
)
from src.application.hockey_races import mark_calendar_synced
from src.ingestion.hockey_sources import MINSK_TZ

SASHA, KATYA, LESHA, VOVA = 9360001, 9360002, 9360003, 9360004
DAY = datetime(2026, 11, 10, 0, 0, tzinfo=MINSK_TZ)


def at(hour: int, minute: int = 0, *, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MINSK_TZ)


@pytest.fixture(autouse=True)
def bot_env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)


@pytest.fixture
def factory(db_session):
    @asynccontextmanager
    async def make():
        yield db_session

    return make


class Outbox:
    """Подмена отправки: что ушло, и что ответить следующему."""

    def __init__(self, answer=SENT) -> None:
        self.sent: list[tuple[int, str, list]] = []
        self.answer = answer

    async def __call__(self, chat_id: int, body: str, buttons) -> str:
        self.sent.append((chat_id, body, buttons))
        return self.answer


async def _match(db_session, mid: str, starts_at: datetime, home="Юность", away="Шахтер") -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                VALUES ('hockeyby', 'extraliga', :mid, :home, :away, :starts_at) RETURNING id
                """),
            {"mid": mid, "home": home, "away": away, "starts_at": starts_at},
        )
    ).scalar_one()


async def _pick(db_session, player: int, match_id: int, **kw) -> None:
    await make_pick(
        db_session,
        player_key=player,
        display_name=kw.pop("name", "Игрок"),
        match_id=match_id,
        now=DAY - timedelta(days=1),
        **kw,
    )


async def _finish(db_session, match_id: int, home: int, away: int, when: datetime) -> None:
    await set_manual_result(db_session, match_id, home_score=home, away_score=away, decided_in="regulation", now=when)
    await score_finished_matches(db_session, now=when)


async def _fan(db_session, player: int, club="Юность", name="Игрок") -> None:
    """Игрок, который на прошлой неделе ходил за клуб, — «своя» команда по умолчанию."""
    old = await _match(db_session, f"old-{player}-{club}", DAY - timedelta(days=5), home=club, away="Неман")
    await make_pick(
        db_session, player_key=player, display_name=name, match_id=old, side="home", now=DAY - timedelta(days=6)
    )
    await set_remind(db_session, player, True, display_name=name)


# ---------- (а) нет хода за 3 часа ----------


@pytest.mark.asyncio
async def test_no_move_reminder_three_hours_before_fan_club_match(db_session, factory) -> None:
    await _fan(db_session, SASHA, name="Саша")
    other = await _match(db_session, "x1", at(19), home="Гомель", away="Брест")
    mine = await _match(db_session, "x2", at(19), home="Юность", away="Шахтер")

    assert await due_notices(db_session, now=at(15, 0)) == []  # раньше чем за 3 часа
    notices = await due_notices(db_session, now=at(16, 5))
    assert [(n.kind, n.player_key, n.match_id) for n in notices] == [("nomove", SASHA, mine)]
    n = notices[0]
    assert n.text == "<b>Юность — Шахтёр</b> сегодня в 19:00. Хода ещё нет — тапни прямо здесь."
    assert [b["text"] for b in n.buttons[0]] == ["Юность", "Шахтёр"]
    assert n.buttons[0][0]["callback_data"] == f"kk:p:{mine}:h"
    assert n.buttons[0][1]["callback_data"] == f"kk:p:{mine}:a"
    assert other not in [x.match_id for x in notices]

    out = Outbox()
    assert await deliver(factory, now=at(16, 5), send=out) == {"sent": 1, "failed": 0, "blocked": 0}
    assert await deliver(factory, now=at(16, 15), send=out) == {"sent": 0, "failed": 0, "blocked": 0}
    assert len(out.sent) == 1


@pytest.mark.asyncio
async def test_no_reminder_when_move_exists_or_off_or_no_club(db_session) -> None:
    await _fan(db_session, SASHA)
    await _fan(db_session, KATYA)
    await _fan(db_session, LESHA)
    m = await _match(db_session, "y1", at(19))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    await set_type(db_session, KATYA, "nomove", False)
    await set_remind(db_session, LESHA, False)
    # Новичок без ходов и без «болею за» — про команду писать не о чем.
    await set_remind(db_session, 9360099, True, display_name="Новичок")
    assert await due_notices(db_session, now=at(16, 5)) == []


@pytest.mark.asyncio
async def test_fan_club_is_explicit_choice_else_most_picked_in_30_days(db_session) -> None:
    # За Юность ходил один раз, за Неман — дважды: «своя» — Неман.
    await set_remind(db_session, SASHA, True, display_name="Саша")
    for i, club in enumerate(("Юность", "Неман", "Неман")):
        old = await _match(db_session, f"f{i}", DAY - timedelta(days=3 + i), home=club, away="Динамо-Минск")
        await make_pick(
            db_session, player_key=SASHA, display_name="Саша", match_id=old, side="home", now=DAY - timedelta(days=10)
        )
    neman = await _match(db_session, "f9", at(19), home="Неман", away="Юность")
    assert [n.match_id for n in await due_notices(db_session, now=at(16, 5))] == [neman]

    # Явное «болею за» сильнее статистики; неизвестный клуб не принимается.
    with pytest.raises(ValueError):
        await set_fav_club(db_session, SASHA, "Несуществующий")
    await set_fav_club(db_session, SASHA, "Шахтер")
    assert await due_notices(db_session, now=at(16, 5)) == []
    shakhter = await _match(db_session, "f10", at(19), home="Юность", away="Шахтер")
    assert [n.match_id for n in await due_notices(db_session, now=at(16, 5))] == [shakhter]
    assert (await get_prefs(db_session, SASHA))["fav_club"] == "Шахтер"


# ---------- (б) итог хода ----------


@pytest.mark.asyncio
async def test_result_message_points_place_and_next_move_button(db_session, factory) -> None:
    for player, name in ((SASHA, "Саша"), (KATYA, "Катя"), (LESHA, "Лёша"), (VOVA, "Вова")):
        await _fan(db_session, player, name=name)
    m = await _match(db_session, "r1", at(19))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=m, home_score=3, away_score=2, now=at(10)
    )
    await make_pick(db_session, player_key=KATYA, display_name="Катя", match_id=m, side="home", now=at(10))
    await make_pick(
        db_session, player_key=LESHA, display_name="Лёша", match_id=m, home_score=4, away_score=1, now=at(10)
    )
    await make_pick(db_session, player_key=VOVA, display_name="Вова", match_id=m, side="away", now=at(10))
    done = at(21, 40)
    await _finish(db_session, m, 3, 2, done)

    by_player = {n.player_key: n for n in await due_notices(db_session, now=done)}
    sasha = by_player[SASHA]
    assert sasha.kind == "result"
    assert sasha.text.startswith("<b>Юность — Шахтёр 3:2.</b> В точку! +50.\nТвоё место в «")
    assert sasha.text.endswith("»: 1-е из 4.")
    assert by_player[KATYA].text.startswith("<b>Юность — Шахтёр 3:2.</b> Есть победитель: +20.")
    assert by_player[VOVA].text.startswith("<b>Юность — Шахтёр 3:2.</b> Мимо. Бывает.")
    labels = [b["text"] for row in sasha.buttons for b in row]
    assert "Следующий ход" in labels and "Таблица" in labels
    assert sasha.buttons[0][0]["callback_data"] == "kk:n"

    out = Outbox()
    assert (await deliver(factory, now=done, send=out))["sent"] == 4
    assert (await deliver(factory, now=done + timedelta(minutes=10), send=out))["sent"] == 0
    # Через 6 часов итог устарел — но и отправленный повторно не уходит.
    assert await due_notices(db_session, now=done + timedelta(hours=7)) == []


@pytest.mark.asyncio
async def test_two_results_at_once_go_as_one_summary_and_are_not_counted_in_budget(db_session, factory) -> None:
    await _fan(db_session, SASHA, name="Саша")
    first = await _match(db_session, "s1", at(12))
    second = await _match(db_session, "s2", at(15), home="Неман", away="Юность")
    for m in (first, second):
        await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(9))
    await _finish(db_session, first, 2, 1, at(14, 30))
    await _finish(db_session, second, 0, 1, at(17, 30))
    notices = await due_notices(db_session, now=at(17, 40))
    assert len(notices) == 1
    assert notices[0].text.startswith("<b>Итоги твоих ходов</b>\n")
    assert notices[0].text.count("\n") == 2
    out = Outbox()
    await deliver(factory, now=at(17, 40), send=out)
    assert len(out.sent) == 1
    # Оба матча заняты: ни один из них не вернётся отдельным итогом.
    assert await due_notices(db_session, now=at(17, 50)) == []


@pytest.mark.asyncio
async def test_result_type_off_blocks_it(db_session) -> None:
    await _fan(db_session, SASHA)
    m = await _match(db_session, "o1", at(19))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    await _finish(db_session, m, 2, 1, at(21, 30))
    await set_type(db_session, SASHA, "result", False)
    assert await due_notices(db_session, now=at(21, 40)) == []
    await set_type(db_session, SASHA, "result", True)
    assert len(await due_notices(db_session, now=at(21, 40))) == 1


# ---------- тишина и бюджет ----------


def test_quiet_hours_are_23_to_09_minsk() -> None:
    assert in_quiet_hours(at(23, 0)) and in_quiet_hours(at(3)) and in_quiet_hours(at(8, 59))
    assert not in_quiet_hours(at(9, 0)) and not in_quiet_hours(at(22, 59))


@pytest.mark.asyncio
async def test_night_result_waits_until_morning(db_session) -> None:
    await _fan(db_session, SASHA)
    m = await _match(db_session, "q1", at(21))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    await _finish(db_session, m, 4, 2, at(23, 40))
    assert await due_notices(db_session, now=at(23, 45)) == []
    assert await due_notices(db_session, now=at(2, 0, day=11)) == []
    morning = await due_notices(db_session, now=at(9, 5, day=11))
    assert [n.kind for n in morning] == ["result"]


@pytest.mark.asyncio
async def test_a_day_with_three_matches_sends_at_most_reminder_plus_summary(db_session, factory) -> None:
    """B2: три матча «своей» команды за день, итоги всех — не больше двух сообщений."""
    await _fan(db_session, SASHA, name="Саша")
    ms = [
        await _match(db_session, "d1", at(12), home="Юность", away="Шахтер"),
        await _match(db_session, "d2", at(16), home="Юность", away="Гомель"),
        await _match(db_session, "d3", at(20), home="Юность", away="Брест"),
    ]
    out = Outbox()
    # Утро: напоминание про первый матч (за три часа до него).
    await deliver(factory, now=at(9, 10), send=out)
    # Остальные напоминания в тот же день не уходят, даже если хода нет.
    await deliver(factory, now=at(13, 10), send=out)
    await deliver(factory, now=at(17, 10), send=out)
    assert [text for _, text, _ in out.sent] == [
        "<b>Юность — Шахтёр</b> сегодня в 12:00. Хода ещё нет — тапни прямо здесь."
    ]
    # Он сделал ходы и дождался итогов всех трёх.
    for m in ms:
        await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(9, 30))
        await _finish(db_session, m, 2, 1, at(22, 0))
    await deliver(factory, now=at(22, 10), send=out)
    assert len(out.sent) == 2
    assert out.sent[1][1].startswith("<b>Итоги твоих ходов</b>")


@pytest.mark.asyncio
async def test_priority_month_final_over_overtaken_over_reminder(db_session) -> None:
    from src.application.hockey_notices import Overtake

    await _fan(db_session, SASHA, name="Саша")
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Офис")
    mid = await _match(db_session, "p1", at(19))
    over = Overtake(
        league.id, "Офис", SASHA, "Катя", 2, mid, scope=("all", ()), starts_at=at(0, day=1), ends_at=at(0, day=30)
    )
    only_over = await due_notices(db_session, now=at(16, 5), overtakes=[over])
    assert [n.kind for n in only_over] == ["overtook"]  # важнее напоминания; в тот же проход оно не уходит


# ---------- (в) тебя обошли ----------


@pytest.mark.asyncio
async def test_overtaken_in_league_is_detected_once_per_change(db_session, factory) -> None:
    await _fan(db_session, SASHA, name="Саша")
    await _fan(db_session, KATYA, name="Катя")
    await _fan(db_session, LESHA, name="Лёша")
    league = await create_league(
        db_session,
        owner_key=SASHA,
        owner_name="Саша",
        name="Офис на Немиге",
        terms=build_terms(scope="all", term="season", now=at(0, day=1)),
        now=at(0, day=1),
    )
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await join_by_code(db_session, player_key=LESHA, display_name="Лёша", code=league.invite_code)
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": at(0, day=1), "l": league.id},
    )
    m1 = await _match(db_session, "v1", at(12), home="Юность", away="Шахтер")
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m1, side="home", now=at(9))
    await make_pick(db_session, player_key=KATYA, display_name="Катя", match_id=m1, side="away", now=at(9))
    await make_pick(db_session, player_key=LESHA, display_name="Лёша", match_id=m1, side="away", now=at(9))
    await _finish(db_session, m1, 3, 1, at(14, 30))
    assert await scan_league_ranks(db_session, now=at(14, 40)) == []  # первый проход только запоминает

    # Следующий матч: Саша мимо, Катя угадала — Катя выше.
    m2 = await _match(db_session, "v2", at(16), home="Неман", away="Юность")
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m2, side="home", now=at(15))
    await make_pick(
        db_session, player_key=KATYA, display_name="Катя", match_id=m2, home_score=0, away_score=2, now=at(15)
    )
    await make_pick(db_session, player_key=LESHA, display_name="Лёша", match_id=m2, side="away", now=at(15))
    await _finish(db_session, m2, 0, 2, at(18, 30))
    found = await scan_league_ranks(db_session, now=at(18, 40))
    assert [(o.player_key, o.by_name, o.rank) for o in found] == [(SASHA, "Катя", 2)]
    # Повторный проход без новых итогов молчит.
    assert await scan_league_ranks(db_session, now=at(18, 50)) == []

    notices = await due_notices(db_session, now=at(18, 50), overtakes=found)
    sasha = next(n for n in notices if n.player_key == SASHA and n.kind == "overtook")
    assert sasha.text.startswith("В лиге «Офис на Немиге» ") and "теперь выше тебя" in sasha.text
    assert any(b.get("callback_data") == "kk:off:ot" for row in sasha.buttons for b in row)


# ---------- (г) финал месяца ----------


@pytest.mark.asyncio
async def test_month_final_message_at_noon_for_top_players(db_session, factory) -> None:
    for player, name in ((SASHA, "Саша"), (KATYA, "Катя"), (LESHA, "Лёша"), (VOVA, "Вова")):
        await _fan(db_session, player, name=name)
    done = await _match(db_session, "m1", at(19, day=5))
    for player, side in ((KATYA, "home"), (VOVA, "away")):
        await make_pick(db_session, player_key=player, display_name="x", match_id=done, side=side, now=at(10, day=5))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=done, home_score=3, away_score=1, now=at(10, day=5)
    )
    await make_pick(
        db_session, player_key=LESHA, display_name="Лёша", match_id=done, home_score=2, away_score=1, now=at(10, day=5)
    )
    await _finish(db_session, done, 3, 1, at(22, 0, day=5))
    last = await _match(db_session, "m2", at(19, day=30), home="Юность", away="Гомель")
    await mark_calendar_synced(db_session, now=at(10, day=29))

    assert [n for n in await due_notices(db_session, now=at(11, 0, day=30)) if n.kind == "mfinal"] == []
    notices = [n for n in await due_notices(db_session, now=at(12, 5, day=30)) if n.kind == "mfinal"]
    by_player = {n.player_key: n for n in notices}
    assert set(by_player) == {SASHA, KATYA, LESHA}  # у Вовы очков нет, он вне тройки
    assert by_player[SASHA].text.startswith(
        "<b>Корона за ноябрь решится сегодня:</b> Юность — Гомель, 19:00, последний матч месяца. "
        "Ты на 1-м месте, Лёша позади на 20 очков."
    )
    assert "до короны 30 очков" in by_player[KATYA].text
    assert by_player[SASHA].buttons[0][0]["callback_data"] == f"kk:p:{last}:h"
    # Не в день финала — тишина.
    assert [n for n in await due_notices(db_session, now=at(12, 5, day=29)) if n.kind == "mfinal"] == []


# ---------- заблокировал бота ----------


@pytest.mark.asyncio
async def test_blocked_bot_is_marked_and_not_written_to_until_return(db_session, factory) -> None:
    await _fan(db_session, SASHA)
    m = await _match(db_session, "b1", at(19))
    out = Outbox(answer=BLOCKED)
    assert await deliver(factory, now=at(16, 5), send=out) == {"sent": 0, "failed": 0, "blocked": 1}
    assert (await get_prefs(db_session, SASHA))["blocked"] is True
    # Следующий матч в тот же день — писать некому.
    await _match(db_session, "b2", at(20), home="Юность", away="Гомель")
    assert await due_notices(db_session, now=at(17, 5)) == []
    # Новый вход (включил напоминания снова) = повторная попытка.
    await set_remind(db_session, SASHA, True)
    assert (await get_prefs(db_session, SASHA))["blocked"] is False
    assert m


@pytest.mark.asyncio
async def test_failed_send_is_not_retried(db_session, factory) -> None:
    await _fan(db_session, SASHA)
    await _match(db_session, "b3", at(19))
    assert (await deliver(factory, now=at(16, 5), send=Outbox(answer=FAILED)))["failed"] == 1
    out = Outbox()
    assert (await deliver(factory, now=at(16, 20), send=out))["sent"] == 0 and out.sent == []
    assert (await get_prefs(db_session, SASHA))["blocked"] is False


# ---------- ход из чата ----------


@pytest.mark.asyncio
async def test_chat_pick_equals_mini_app_pick_and_closes_with_the_match(db_session) -> None:
    m = await _match(db_session, "c1", at(19))
    got = await chat_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="h", now=at(16))
    assert (got.status, got.side, got.home, got.away) == ("ok", "home", "Юность", "Шахтёр")
    chat_row = (
        await db_session.execute(
            text("SELECT side, home_score, doubled FROM hockey_picks WHERE player_key = :p"), {"p": SASHA}
        )
    ).one()
    # То же самое пишет use case Mini App.
    await make_pick(db_session, player_key=KATYA, display_name="Катя", match_id=m, side="home", now=at(16))
    app_row = (
        await db_session.execute(
            text("SELECT side, home_score, doubled FROM hockey_picks WHERE player_key = :p"), {"p": KATYA}
        )
    ).one()
    assert tuple(chat_row) == tuple(app_row) == ("home", None, False)
    # Смена стороны до старта допустима.
    again = await chat_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="a", now=at(18))
    assert again.side == "away"
    # После старта кнопка отвечает «закрыто» и ничего не пишет.
    late = await chat_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="h", now=at(19, 30))
    assert late.status == "closed"
    side = (
        await db_session.execute(text("SELECT side FROM hockey_picks WHERE player_key = :p"), {"p": SASHA})
    ).scalar_one()
    assert side == "away"
    assert (
        await chat_pick(db_session, player_key=SASHA, display_name="С", match_id=999999, side="h", now=at(16))
    ).status == "missing"


@pytest.mark.asyncio
async def test_next_move_is_nearest_open_match_of_fan_club(db_session) -> None:
    await _fan(db_session, SASHA)
    await _match(db_session, "n1", at(20, day=11), home="Гомель", away="Брест")
    mine = await _match(db_session, "n2", at(19, day=12))
    nxt = await next_move(db_session, player_key=SASHA, now=at(22))
    assert nxt is not None and nxt.match_id == mine
    assert nxt.buttons[0][0]["callback_data"] == f"kk:p:{mine}:h"
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=mine, side="home", now=at(22))
    # «Своя» команда закрыта — берём любой открытый матч.
    fallback = await next_move(db_session, player_key=SASHA, now=at(22))
    assert fallback is not None and fallback.match_id != mine


# ---------- «лига продлена» ----------


@pytest.mark.asyncio
async def test_extend_notifies_every_member_except_the_owner_once(db_session, factory) -> None:
    league = await create_league(
        db_session,
        owner_key=SASHA,
        owner_name="Саша",
        name="Офис",
        terms=build_terms(scope="all", term="season", now=at(0, day=1)),
        now=at(0, day=1),
    )
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await join_by_code(db_session, player_key=LESHA, display_name="Лёша", code=league.invite_code)
    await set_type(db_session, LESHA, "league", False)
    fresh, created = await extend_league(db_session, league_id=league.id, player_key=SASHA, now=at(12))
    assert created
    out = Outbox()
    counts = await deliver_league_notices(factory, now=at(12, 5), send=out)
    assert counts["sent"] == 1 and counts["skipped"] == 1
    chat, body, buttons = out.sent[0]
    assert chat == KATYA
    assert body.startswith("<b>Лига «Офис» продлена.</b>") and body.endswith("Выйти можно в один тап.")
    assert buttons[1][0]["callback_data"] == f"kk:lv:{fresh.id}"
    assert (await deliver_league_notices(factory, now=at(12, 30), send=out))["sent"] == 0
    # Повторное «Продлить» ничего нового не рассылает.
    await extend_league(db_session, league_id=league.id, player_key=SASHA, now=at(13))
    assert (await deliver_league_notices(factory, now=at(13, 5), send=out))["sent"] == 0
    assert len(out.sent) == 1


@pytest.mark.asyncio
async def test_default_on_for_anyone_with_a_move_off_stays_off(db_session) -> None:
    """Решение координатора: без настроек пишем всем, у кого есть ход; без ходов — нет; явное «выкл» уважаем."""
    old = await _match(db_session, "df0", DAY - timedelta(days=5), home="Юность", away="Неман")
    for player in (SASHA, KATYA):
        await make_pick(
            db_session, player_key=player, display_name="И", match_id=old, side="home", now=DAY - timedelta(days=6)
        )
    await db_session.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:p, 'Без ходов')"), {"p": VOVA}
    )
    await set_remind(db_session, KATYA, False)
    mine = await _match(db_session, "df1", at(19))
    assert (await get_prefs(db_session, SASHA))["on"] is True  # строки настроек нет — включено
    notices = await due_notices(db_session, now=at(16, 5))
    assert [(n.player_key, n.match_id) for n in notices] == [(SASHA, mine)]
