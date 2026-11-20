"""TASK-334 S6: бот «Кто кого» — четыре повода, дневной бюджет, ход из чата, блокировка, «лига продлена»."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_leagues import build_terms, create_league, extend_league, join_by_code
from src.application.hockey_matches import set_manual_result
from src.application import hockey_notices
from src.application.hockey_notices import (
    BLOCKED,
    EveningIO,
    FAILED,
    RETRY,
    SENT,
    chat_pick,
    deliver,
    deliver_league_notices,
    due_notices,
    get_prefs,
    in_quiet_hours,
    mark_blocked,
    next_move,
    scan_league_ranks,
    set_fav_club,
    set_remind,
    set_type,
    tribune_line,
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


@pytest.fixture(autouse=True)
def fresh_retry_counter() -> None:
    hockey_notices._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    @asynccontextmanager
    async def make():
        yield db_session

    return make


class BoardIO:
    """Подмена отправки табло: новые сообщения (с номером) и правки."""

    def __init__(self, edit_answer=SENT) -> None:
        self.sent: list[tuple[int, str, list, int]] = []
        self.edits: list[tuple[int, int, str, list]] = []
        self.edit_answer = edit_answer
        self._next = 100

        async def send(chat_id, body, buttons):
            self._next += 1
            self.sent.append((chat_id, body, buttons, self._next))
            return SENT, self._next

        async def edit(chat_id, message_id, body, buttons):
            self.edits.append((chat_id, message_id, body, buttons))
            return self.edit_answer

        self.io = EveningIO(send, edit)


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
    assert n.text == "<b>Юность — Шахтёр</b> сегодня в 19:00. КТО КОГО? 🏒"
    assert [b["text"] for b in n.buttons[0]] == ["Сыграть"]
    assert n.buttons[0][0]["url"].endswith(f"?start=kkn_{mine}") or "kkn" in n.buttons[0][0]["url"]
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
    from src.application.kk_evening import quips

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

    # Свежий итог в чат не уходит (буфер RESULT_SEND_DELAY): его можно поправить до рассылки.
    assert await due_notices(db_session, now=done) == []
    assert await due_notices(db_session, now=done + hockey_notices.RESULT_SEND_DELAY - timedelta(seconds=1)) == []
    ready = done + hockey_notices.RESULT_SEND_DELAY
    by_player = {n.player_key: n for n in await due_notices(db_session, now=ready)}
    sasha = by_player[SASHA]
    assert sasha.kind == "result"
    # Один матч за вечер — сразу «Итог вечера» (PDEC-038): матч, твой ход, очки; ниже — место «было → стало».
    assert sasha.text.startswith(
        "<b>Юность — Шахтёр 3:2</b> · твой 3:2 · в точку! <b>+50</b>\n\nОбщая таблица: <b>1-е</b> из 4"
    )
    # Первое появление в таблице — событие: хвост по месту и фраза первого вечера.
    assert "<b>1-е</b> из 4 — уже на подиуме" in sasha.text
    assert any(q in sasha.text for q in quips()["first"])
    assert by_player[KATYA].text.startswith("<b>Юность — Шахтёр 3:2</b> · твой Юность · <b>+20</b>")
    assert by_player[VOVA].text.startswith("<b>Юность — Шахтёр 3:2</b> · твой Шахтёр · 0")
    # Срез своей команды повторяет общую таблицу — второй строкой не пишем.
    assert "Таблица «" not in sasha.text
    # Фраза вечера — из коллекции, курсивом; у одного матча без «{n}».
    assert "<i>" in sasha.text and "{n}" not in sasha.text
    labels = [b["text"] for row in sasha.buttons for b in row]
    assert "Таблица" in labels and "Отключить такие сообщения" in labels
    assert sasha.buttons[0][-1]["url"].endswith("startapp=kktb")

    out = Outbox()
    assert (await deliver(factory, now=ready, send=out))["sent"] == 4
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
    text = notices[0].text
    # Весь вечер готов разом — табло не создаём, сразу «Итог вечера» со строками матчей (PDEC-038).
    assert notices[0].evening.step.action == "final"
    assert text.startswith("<b>Вечер закрыт: +20</b> · 1 из 2\n\n")
    assert "🎯 <b>Юность — Шахтёр 2:1</b> · твой Юность · <b>+20</b>" in text
    assert "❌ <b>Неман — Юность 0:1</b> · твой Неман · 0" in text
    assert text.count("Общая таблица") == 1
    out = Outbox()
    await deliver(factory, now=at(17, 40), send=out)
    assert len(out.sent) == 1
    # Оба матча и «Итог вечера» заняты: ни итог, ни вечер второй раз не уйдут.
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
    assert [text for _, text, _ in out.sent] == ["<b>Юность — Шахтёр</b> сегодня в 12:00. КТО КОГО? 🏒"]
    # Ходы на все три; итоги приходят по одному — табло вечера (PDEC-038).
    for m in ms:
        await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(9, 30))
    io = BoardIO()
    await _finish(db_session, ms[0], 2, 1, at(14, 30))
    await deliver(factory, now=at(14, 40), send=out, evening_io=io.io)
    # Первый итог — новое сообщение-табло (со звуком): 1 из 3, остальные ждут.
    assert len(io.sent) == 1 and not io.edits
    assert "· 1 из 3 твоих матчей" in io.sent[0][1] and "⏳ Юность — Гомель" in io.sent[0][1]
    await _finish(db_session, ms[1], 2, 1, at(18, 30))
    await deliver(factory, now=at(18, 40), send=out, evening_io=io.io)
    # Второй — правка того же табло, без нового сообщения.
    assert len(io.sent) == 1 and len(io.edits) == 1
    assert io.edits[0][1] == io.sent[0][3] and "· 2 из 3 твоих матчей" in io.edits[0][2]
    await _finish(db_session, ms[2], 2, 1, at(22, 30))
    await deliver(factory, now=at(22, 40), send=out, evening_io=io.io)
    # Последний — финальная правка табло и одно новое «Итог вечера».
    assert len(io.edits) == 2 and "За вечер: <b>+60</b>" in io.edits[1][2]
    assert len(io.sent) == 2 and io.sent[1][1].startswith("<b>Вечер закрыт: +60</b> · 3 из 3")
    # Повторный проход ничего не шлёт и не правит.
    await deliver(factory, now=at(22, 50), send=out, evening_io=io.io)
    assert len(io.sent) == 2 and len(io.edits) == 2
    # В обычный канал за день — только утреннее напоминание.
    assert len(out.sent) == 1


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
    assert by_player[SASHA].buttons[0][0]["text"] == "Сыграть"
    assert "kkn" in by_player[SASHA].buttons[0][0]["url"]
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


class Script:
    """Отправка по сценарию: каждому вызову — следующий ответ, последний повторяется."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.calls = 0

    async def __call__(self, chat_id: int, body: str, buttons) -> str:
        answer = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return answer


@pytest.mark.asyncio
async def test_temporary_error_releases_notice_and_next_pass_resends(db_session, factory) -> None:
    await _fan(db_session, SASHA)
    await _match(db_session, "r1", at(19))
    out = Script(RETRY, SENT)
    first = await deliver(factory, now=at(16, 5), send=out)
    assert first["sent"] == 0 and first["failed"] == 0 and first["retry"] == 1
    assert (await db_session.execute(text("SELECT COUNT(*) FROM hockey_notices"))).scalar_one() == 0
    assert (await deliver(factory, now=at(16, 15), send=out))["sent"] == 1
    assert (await deliver(factory, now=at(16, 25), send=out))["sent"] == 0 and out.calls == 2


@pytest.mark.asyncio
async def test_retries_are_capped_then_notice_is_failed_for_good(db_session, factory) -> None:
    await _fan(db_session, SASHA)
    await _match(db_session, "r2", at(19))
    out = Script(RETRY)
    for minute in range(hockey_notices.MAX_ATTEMPTS - 1):
        assert (await deliver(factory, now=at(16, 5 + minute), send=out))["retry"] == 1
    last = await deliver(factory, now=at(16, 20), send=out)
    assert last["failed"] == 1 and "retry" not in last
    assert (await deliver(factory, now=at(16, 30), send=out))[
        "failed"
    ] == 0 and out.calls == hockey_notices.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_temporary_error_on_preclaimed_moved_notice_keeps_it_due(db_session, factory) -> None:
    await _fan(db_session, SASHA)
    m = await _match(db_session, "r3", at(19))
    await db_session.execute(
        text("INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:p, :m, 'moved')"), {"p": SASHA, "m": m}
    )
    out = Script(RETRY, SENT)
    assert (await deliver(factory, now=at(12, 5), send=out))["retry"] == 1
    assert (await deliver(factory, now=at(12, 15), send=out))["sent"] == 1


@pytest.mark.asyncio
async def test_moved_notice_is_dropped_once_the_match_is_cancelled(db_session, factory) -> None:
    """Перенесли, письмо ждало (тихие часы), а матч отменили: «перенесли на …» с кнопками хода не уходит."""
    await _fan(db_session, SASHA)
    m = await _match(db_session, "r4", at(19))
    await db_session.execute(
        text("INSERT INTO hockey_notices (player_key, match_id, kind) VALUES (:p, :m, 'moved')"), {"p": SASHA, "m": m}
    )
    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :m"), {"m": m})
    out = Script(SENT)
    assert (await deliver(factory, now=at(12, 5), send=out)).get("sent", 0) == 0 and out.calls == 0


@pytest.mark.asyncio
async def test_temporary_error_returns_league_notice_to_queue(db_session, factory) -> None:
    league = await create_league(
        db_session,
        owner_key=SASHA,
        owner_name="Саша",
        name="Офис",
        terms=build_terms(scope="all", term="season", now=at(0, day=1)),
        now=at(0, day=1),
    )
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await extend_league(db_session, league_id=league.id, player_key=SASHA, now=at(12))
    out = Script(RETRY, SENT)
    assert (await deliver_league_notices(factory, now=at(12, 5), send=out))["retry"] == 1
    assert (await deliver_league_notices(factory, now=at(12, 15), send=out))["sent"] == 1


class _FakeBot:
    def __init__(self, *errors) -> None:
        self.errors = list(errors)
        self.sent = 0

    async def send_message(self, **kwargs) -> None:
        if self.errors:
            raise self.errors.pop(0)
        self.sent += 1


@pytest.fixture
def sender(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(sec: float) -> None:
        sleeps.append(sec)

    monkeypatch.setattr(hockey_notices.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(hockey_notices, "_THROTTLE_SEC", 0)

    def use(bot):
        async def get():
            return bot

        monkeypatch.setattr(hockey_notices, "_client_bot", get)
        return sleeps

    return use


@pytest.mark.asyncio
async def test_sender_waits_retry_after_and_resends(sender) -> None:
    from aiogram.exceptions import TelegramRetryAfter

    bot = _FakeBot(TelegramRetryAfter(method=None, message="flood", retry_after=3))
    sleeps = sender(bot)
    assert await hockey_notices.send_via_client_bot(1, "t", []) == SENT
    assert sleeps == [3] and bot.sent == 1


@pytest.mark.asyncio
async def test_sender_long_retry_after_is_not_waited_but_retried_later(sender) -> None:
    from aiogram.exceptions import TelegramRetryAfter

    bot = _FakeBot(TelegramRetryAfter(method=None, message="flood", retry_after=600))
    sleeps = sender(bot)
    assert await hockey_notices.send_via_client_bot(1, "t", []) == RETRY
    assert sleeps == [] and bot.sent == 0


@pytest.mark.asyncio
async def test_sender_network_and_server_errors_are_retry_bad_request_is_failed(sender) -> None:
    from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramServerError

    for error, expected in (
        (TelegramNetworkError(method=None, message="timeout"), RETRY),
        (TelegramServerError(method=None, message="502"), RETRY),
        (TelegramBadRequest(method=None, message="chat not found"), FAILED),
    ):
        sender(_FakeBot(error))
        assert await hockey_notices.send_via_client_bot(1, "t", []) == expected


@pytest.mark.asyncio
async def test_sender_throttles_between_messages(sender, monkeypatch) -> None:
    sleeps = sender(_FakeBot())
    monkeypatch.setattr(hockey_notices, "_THROTTLE_SEC", 0.04)
    monkeypatch.setattr(hockey_notices, "_last_send", hockey_notices.time.monotonic())
    await hockey_notices.send_via_client_bot(1, "t", [])
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 0.04


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
    assert nxt.buttons[0][0]["text"] == "Сыграть"
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


# ---------- «мы ошиблись с итогом»: исправление уже разосланного итога ----------


async def _resent_world(db_session, factory):
    """Матч 3:2, итог разослан SASHA (точный счёт), KATYA (сторона), VOVA; у LESHA тип «итоги» выключен с начала."""
    for player, name in ((SASHA, "Саша"), (KATYA, "Катя"), (LESHA, "Лёша"), (VOVA, "Вова")):
        await _fan(db_session, player, name=name)
    await set_type(db_session, LESHA, "result", False)
    m = await _match(db_session, "rs1", at(19))
    await make_pick(
        db_session, player_key=SASHA, display_name="Саша", match_id=m, home_score=3, away_score=2, now=at(10)
    )
    await make_pick(db_session, player_key=KATYA, display_name="Катя", match_id=m, side="home", now=at(10))
    await make_pick(db_session, player_key=LESHA, display_name="Лёша", match_id=m, side="home", now=at(10))
    await make_pick(db_session, player_key=VOVA, display_name="Вова", match_id=m, side="away", now=at(10))
    await _finish(db_session, m, 3, 2, at(21, 40))
    out = Outbox()
    assert (await deliver(factory, now=at(21, 50), send=out))["sent"] == 3
    return m, out


async def _correct(db_session, m: int, home: int, away: int, when: datetime, decided: str = "regulation") -> None:
    await set_manual_result(db_session, m, home_score=home, away_score=away, decided_in=decided, now=when)
    await score_finished_matches(db_session, now=when)


@pytest.mark.asyncio
async def test_corrected_result_reaches_only_those_who_got_the_old_one_once(db_session, factory) -> None:
    m, _ = await _resent_world(db_session, factory)
    await set_type(db_session, VOVA, "result", False)  # отписался уже после итога: исправление ему не нужно
    await _correct(db_session, m, 2, 3, at(22, 0))

    out = Outbox()
    assert (await deliver(factory, now=at(22, 10), send=out))["sent"] == 2
    by_player = {chat: body for chat, body, _ in out.sent}
    assert set(by_player) == {SASHA, KATYA}  # LESHA итог не получал, VOVA отписан
    assert by_player[SASHA] == (
        "Мы ошиблись с итогом: Юность — Шахтёр закончился 2:3, а не 3:2. Твои очки за матч: +0."
    )
    assert by_player[KATYA].startswith("Мы ошиблись с итогом: Юность — Шахтёр закончился 2:3, а не 3:2.")
    labels = [b["text"] for row in out.sent[0][2] for b in row]
    assert "Таблица" in labels
    # Один раз на игрока и матч: ни повтор, ни вторая правка не шлют снова.
    assert (await deliver(factory, now=at(22, 20), send=out))["sent"] == 0
    await _correct(db_session, m, 5, 1, at(22, 30))
    assert (await deliver(factory, now=at(22, 40), send=out))["sent"] == 0


@pytest.mark.asyncio
async def test_same_score_or_returning_to_it_sends_nothing(db_session, factory) -> None:
    m, _ = await _resent_world(db_session, factory)
    await _correct(db_session, m, 3, 2, at(22, 0), decided="ot")  # тот же счёт, другой способ окончания
    assert (await deliver(factory, now=at(22, 10), send=Outbox()))["sent"] == 0
    await _correct(db_session, m, 2, 3, at(22, 15))
    await _correct(db_session, m, 3, 2, at(22, 20))  # вернули к тому, что клиенты уже видели
    assert (await deliver(factory, now=at(22, 30), send=Outbox()))["sent"] == 0


@pytest.mark.asyncio
async def test_correction_in_quiet_hours_waits_until_morning(db_session, factory) -> None:
    m, _ = await _resent_world(db_session, factory)
    await _correct(db_session, m, 2, 3, at(23, 30))
    out = Outbox()
    assert (await deliver(factory, now=at(23, 40), send=out))["sent"] == 0
    assert (await deliver(factory, now=at(2, 0, day=11), send=out))["sent"] == 0
    # Утром, много часов спустя (окно свежести итога для исправления не действует), оно уходит.
    assert (await deliver(factory, now=at(9, 5, day=11), send=out))["sent"] == 3
    assert all(body.startswith("Мы ошиблись с итогом") for _, body, _ in out.sent)


@pytest.mark.asyncio
async def test_blocked_player_gets_no_correction_and_unchanged_points_are_not_mentioned(db_session, factory) -> None:
    m, _ = await _resent_world(db_session, factory)
    await mark_blocked(db_session, VOVA, now=at(22, 0))
    await _correct(db_session, m, 4, 2, at(22, 5))  # победитель тот же: у KATYA очки не меняются
    out = Outbox()
    assert (await deliver(factory, now=at(22, 15), send=out))["sent"] == 2
    by_player = {chat: body for chat, body, _ in out.sent}
    assert VOVA not in by_player
    assert by_player[KATYA] == "Мы ошиблись с итогом: Юность — Шахтёр закончился 4:2, а не 3:2."
    assert "очки" not in by_player[KATYA]
    assert "очки" in by_player[SASHA]


# ---------- «Трибуна» в итоге ----------


def _tribune(**kw) -> str:
    base = dict(
        home="Неман",
        away="Шахтер",
        final_home=2,
        final_away=3,
        side="away",
        points=20,
        home_picks=114,
        away_picks=34,
        same_exact=0,
    )
    base.update(kw)
    return tribune_line(**base)


def test_tribune_line_cases() -> None:
    assert _tribune() == "Победителя угадали 23% игроков — и ты в их числе."
    assert _tribune(side="home", points=0) == "Трибуна тоже промахнулась: 77% были за Неман."
    assert _tribune(final_home=4, final_away=1, side="away", points=0) == "Победителя угадали 77% игроков."
    assert _tribune(points=50) == "Такой счёт больше никто из 148 не назвал."
    assert _tribune(points=50, same_exact=3) == "Такой счёт назвали ещё 3 из 148."
    # Меньше 8 ходов — строки нет, ровно 8 — есть; «Шахтер» из базы — «Шахтёр» в тексте.
    assert _tribune(home_picks=4, away_picks=3) == ""
    assert _tribune(home_picks=4, away_picks=4, side="away", final_home=2, final_away=3, points=20) == (
        "Победителя угадали 50% игроков — и ты в их числе."
    )
    assert _tribune(home_picks=5, away_picks=15, side="away", final_home=4, final_away=1, points=0) == (
        "Трибуна тоже промахнулась: 75% были за Шахтёр."
    )
    # Гости — остаток до 100 после округлённой доли хозяев, как в Mini App: 1 из 40 хозяев → 3%, гостей 97%, не 98%.
    assert _tribune(home_picks=1, away_picks=39, final_home=2, final_away=3, side="away") == (
        "Победителя угадали 97% игроков — и ты в их числе."
    )
    # Половина вверх, как Math.round в Mini App.
    assert _tribune(home_picks=1, away_picks=39, final_home=3, final_away=2, side="home") == (
        "Победителя угадали 3% игроков — и ты в их числе."
    )


@pytest.mark.asyncio
async def test_result_message_has_tribune_line_from_twenty_moves(db_session) -> None:
    await _fan(db_session, SASHA, name="Саша")
    m = await _match(db_session, "trib", at(19))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="away", now=at(10))
    await make_pick(db_session, player_key=KATYA, display_name="Катя", match_id=m, side="away", now=at(10))
    for i in range(18):
        await make_pick(
            db_session, player_key=9361000 + i, display_name=f"Игрок {i}", match_id=m, side="home", now=at(10)
        )
    done = at(21, 40)
    await _finish(db_session, m, 2, 3, done)
    notices = await due_notices(db_session, now=done + hockey_notices.RESULT_SEND_DELAY)
    sasha = next(n for n in notices if n.player_key == SASHA)
    # Вечер из одного матча: «Трибуна» — сразу под строкой матча в «Итоге вечера».
    assert sasha.text.startswith(
        "<b>Юность — Шахтёр 2:3</b> · твой Шахтёр · <b>+20</b>\n" "Победителя угадали 10% игроков — и ты в их числе."
    )


# ---------- табло вечера: крайние случаи (PDEC-038, TASK-434) ----------


@pytest.mark.asyncio
async def test_stuck_match_closes_the_evening_after_four_hours_and_its_result_comes_later(db_session, factory) -> None:
    await _fan(db_session, SASHA, name="Саша")
    a = await _match(db_session, "st1", at(15))
    b = await _match(db_session, "st2", at(16), home="Неман", away="Гомель")
    for m in (a, b):
        await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    io = BoardIO()
    await _finish(db_session, a, 2, 1, at(17, 30))
    await deliver(factory, now=at(17, 40), send=Outbox(), evening_io=io.io)
    assert len(io.sent) == 1  # табло: 1 из 2
    # Итога второго нет и через 4 часа после начала — вечер закрываем без него.
    await deliver(factory, now=at(20, 1), send=Outbox(), evening_io=io.io)
    assert len(io.sent) == 2 and io.sent[1][1].startswith("<b>Вечер закрыт: +20</b>")
    assert "итог позже" in io.edits[-1][2]
    # Итог появился — короткое отдельное сообщение, вечер второй раз не закрывается.
    await _finish(db_session, b, 0, 3, at(21, 30))
    await deliver(factory, now=at(21, 40), send=Outbox(), evening_io=io.io)
    assert len(io.sent) == 3 and io.sent[2][1].startswith("Итог позже, чем вечер: ❌ <b>Неман — Гомель 0:3</b>")
    await deliver(factory, now=at(21, 50), send=Outbox(), evening_io=io.io)
    assert len(io.sent) == 3


@pytest.mark.asyncio
async def test_deleted_board_is_sent_anew_and_its_number_is_kept(db_session, factory) -> None:
    from src.application.hockey_notices import GONE
    from src.application.kk_evening import load_board

    await _fan(db_session, SASHA, name="Саша")
    ms = [await _match(db_session, f"gn{i}", at(14 + 2 * i)) for i in range(3)]
    for m in ms:
        await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    io = BoardIO(edit_answer=GONE)  # человек удалил табло: править нечего
    await _finish(db_session, ms[0], 2, 1, at(16, 30))
    await deliver(factory, now=at(16, 40), send=Outbox(), evening_io=io.io)
    await _finish(db_session, ms[1], 2, 1, at(18, 30))
    await deliver(factory, now=at(18, 40), send=Outbox(), evening_io=io.io)
    assert len(io.edits) == 1 and len(io.sent) == 2  # правка не вышла — новое табло
    board = await load_board(db_session, player_key=SASHA, day=at(12).date())
    assert board is not None and board.message_id == io.sent[1][3]


@pytest.mark.asyncio
async def test_temporary_failure_releases_the_evening_and_the_next_pass_sends_it_once(db_session, factory) -> None:
    await _fan(db_session, SASHA, name="Саша")
    m = await _match(db_session, "tf1", at(19))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    await _finish(db_session, m, 2, 1, at(21, 30))
    calls: list[str] = []

    async def flaky(chat_id, body, buttons):
        calls.append(body)
        return (RETRY, None) if len(calls) == 1 else (SENT, 7)

    async def no_edit(*_a):
        return SENT

    io = EveningIO(flaky, no_edit)
    assert (await deliver(factory, now=at(21, 40), send=Outbox(), evening_io=io))["retry"] == 1
    assert (await deliver(factory, now=at(21, 45), send=Outbox(), evening_io=io))["sent"] == 1
    assert (await deliver(factory, now=at(21, 50), send=Outbox(), evening_io=io))["sent"] == 0
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_overtaken_notice_is_not_sent_right_after_the_evening_summary(db_session, factory) -> None:
    from src.application.hockey_notices import Overtake

    await _fan(db_session, SASHA, name="Саша")
    m = await _match(db_session, "ov1", at(19))
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, side="home", now=at(10))
    await _finish(db_session, m, 2, 1, at(21, 30))
    await deliver(factory, now=at(21, 40), send=Outbox(), evening_io=BoardIO().io)
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="Офис")
    over = Overtake(
        league.id, "Офис", SASHA, "Катя", 2, m, scope=("all", ()), starts_at=at(0, day=1), ends_at=at(0, day=30)
    )
    assert [n.kind for n in await due_notices(db_session, now=at(22, 0), overtakes=[over])] == []
    # Через 6 часов после «Итога вечера» — снова можно (утро, вне тихих часов).
    later = [n.kind for n in await due_notices(db_session, now=at(10, 0, day=11), overtakes=[over])]
    assert later == ["overtook"]


def test_quips_have_no_betting_words_and_cover_every_situation() -> None:
    from src.application.kk_evening import pick_quip, quips

    banned = ("ставк", "постав", "отыгра", "выигрыш", "коэф", "кэф", "банк")
    pool = quips()
    for kind in ("first", "exact", "hit", "perfect", "zero", "mixed", "climbed", "dropped", "league_top"):
        assert pool[kind], kind
        for q in pool[kind]:
            assert not any(w in q.lower() for w in banned), q
    # Один матч — без «{n}»; два вечера подряд одна и та же фраза не выпадает.
    assert "{n}" not in (pick_quip("zero", player_key=1, day=DAY.date(), n=1) or "")
    for player in range(50):
        today = pick_quip("mixed", player_key=player, day=DAY.date(), n=3)
        yesterday = pick_quip("mixed", player_key=player, day=DAY.date() - timedelta(days=1), n=3)
        assert today != yesterday
