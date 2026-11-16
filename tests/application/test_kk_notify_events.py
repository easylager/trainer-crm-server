"""TASK-426 срезы 2–4: поводы invite / comeback / week / month / consent, пауза, согласие, допуск и перепроверка."""

from __future__ import annotations

from datetime import timedelta

import pytest
from kk_notify_helpers import (
    KATYA,
    LESHA,
    SASHA,
    Outbox,
    at,
    make_factory,
    seed_final,
    seed_match,
    seed_notice,
    seed_pick,
    seed_player,
    seed_scored,
)
from sqlalchemy import text

from src.application import hockey_notices as hn
from src.application import kk_notify_events as ev
from src.application import kk_notify_gate as gate
from src.application import kk_notify_texts as tx
from src.application.kk_notify import dispatch, run_tick
from src.application.kk_notify_gate import GateConfig, admit
from src.application.kk_notify_phase import Phase, load_one

NB = " "
ALL_KINDS = frozenset({"invite", "comeback", "week", "month", "consent"})
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=ALL_KINDS)
WED = at(10, 0, day=11)  # среда
REG = at(10, day=1)


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    hn._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


def plain(value: str) -> str:
    return value.replace(NB, "~")


async def active_player(db, key=SASHA, *, days_ago=2, consent=True, now=WED) -> None:
    """Игрок с согласием, который ходил ``days_ago`` суток назад за «Юность» (она и «своя» команда)."""
    await seed_player(db, key, registered=REG, notify_consent=consent) if consent is not None else await seed_player(
        db, key, registered=REG
    )
    old = await seed_match(db, now - timedelta(days=days_ago) + timedelta(hours=2), home="Юность", away="Неман")
    await seed_pick(db, key, now - timedelta(days=days_ago), match_id=old)


# ---------- 1. матч сегодня или завтра ----------


@pytest.mark.asyncio
async def test_invite_today_text_and_buttons(db_session) -> None:
    await active_player(db_session)
    mid = await seed_match(db_session, at(19, 30, day=11), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    assert (p.notice.kind, p.notice.player_key, p.notice.match_id) == ("invite", SASHA, mid)
    assert plain(p.notice.text) == "<b>Юность~— Шахтёр</b> сегодня в~19:30. Твой ход?"
    first = [b["text"] for b in p.notice.buttons[0]]
    assert first == ["Юность", "Шахтёр"]
    flat = [b["text"] for row in p.notice.buttons for b in row]
    assert flat[-1] == "Не присылать" and "Таблица" in flat


@pytest.mark.asyncio
async def test_invite_tomorrow_wording(db_session) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(17, day=12), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    assert plain(p.notice.text) == "<b>Юность~— Шахтёр</b> завтра в~17:00. Твой ход?"


@pytest.mark.asyncio
async def test_invite_morning_window_boundaries(db_session) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    assert await ev.produce_invite(db_session, now=at(8, 59, day=11)) == []
    assert len(await ev.produce_invite(db_session, now=at(9, 0, day=11))) == 1
    assert len(await ev.produce_invite(db_session, now=at(10, 59, day=11))) == 1
    assert await ev.produce_invite(db_session, now=at(11, 0, day=11)) == []


@pytest.mark.asyncio
async def test_invite_needs_three_hours_before_match(db_session) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(13, 0, day=11), home="Юность", away="Шахтер")
    assert len(await ev.produce_invite(db_session, now=WED)) == 1  # ровно 3 часа
    assert await ev.produce_invite(db_session, now=at(10, 1, day=11)) == []  # меньше трёх часов


@pytest.mark.asyncio
async def test_invite_skips_picked_match_other_clubs_and_non_active(db_session) -> None:
    await active_player(db_session)
    mid = await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    await seed_match(db_session, at(19, day=11), home="Гомель", away="Брест")  # не «своя» команда
    await seed_pick(db_session, SASHA, at(9, 30, day=11), match_id=mid)
    assert await ev.produce_invite(db_session, now=WED) == []
    # остывающий (8 суток без хода) приглашения «матч сегодня» не получает — для него возврат
    await active_player(db_session, KATYA, days_ago=8)
    await seed_match(db_session, at(20, day=11), home="Юность", away="Динамо-Минск")
    assert KATYA not in [p.notice.player_key for p in await ev.produce_invite(db_session, now=WED)]


@pytest.mark.asyncio
@pytest.mark.parametrize("consent", [None, False])
async def test_invite_needs_consent(db_session, consent) -> None:
    await active_player(db_session, consent=consent)
    await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    assert await ev.produce_invite(db_session, now=WED) == []


@pytest.mark.asyncio
async def test_invite_day_word_is_computed_at_send_time(db_session) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(17, day=12), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    assert "завтра" in p.render(WED)
    assert "сегодня" in p.render(at(10, 0, day=12))  # отправка уже на следующие сутки: матч «сегодня»


@pytest.mark.asyncio
async def test_invite_rechecked_right_before_sending(db_session, factory) -> None:
    await active_player(db_session)
    mid = await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    out = Outbox()

    async def go(now):
        return await dispatch(factory, p, phase="active", tick_at=now, send=out, config=CFG, clock=lambda: now)

    assert (await go(at(11, 0, day=11))).reason == "stale:out_of_window"
    assert (await go(at(16, 30, day=11))).reason in ("stale:out_of_window",)
    await seed_pick(db_session, SASHA, at(10, 0, day=11), match_id=mid)  # ход сделан, пока сообщение ждало
    assert (await go(at(10, 0, day=11))).reason == "stale:has_pick"
    assert out.sent == []


@pytest.mark.asyncio
async def test_invite_too_close_at_send_time(db_session, factory) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(13, 0, day=11), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    out = Outbox()
    late = at(10, 5, day=11)
    result = await dispatch(factory, p, phase="active", tick_at=late, send=out, config=CFG, clock=lambda: late)
    assert result.reason == "stale:too_close" and out.sent == []


# ---------- 2. возврат ----------


def test_comeback_ladder_days() -> None:
    steps = {d: ev.comeback_step(d) for d in (0, 2, 3, 9, 10, 29, 30, 31, 60)}
    assert steps == {0: None, 2: None, 3: 1, 9: 1, 10: 2, 29: 2, 30: 3, 31: None, 60: None}


@pytest.mark.asyncio
async def test_comeback_three_days_text_with_weekday(db_session) -> None:
    await active_player(db_session, days_ago=3)
    await seed_match(db_session, at(17, day=14), home="Юность", away="Шахтер")  # суббота
    [p] = await ev.produce_comeback(db_session, now=WED)
    assert p.notice.kind == "comeback"
    assert plain(p.notice.text) == "<b>Юность~— Шахтёр</b> в~субботу в~17:00. Твой ход?"


@pytest.mark.asyncio
async def test_comeback_requires_match_within_six_days_and_no_pick(db_session) -> None:
    await active_player(db_session, days_ago=3)
    far = await seed_match(db_session, at(10, 0, day=17) + timedelta(minutes=1), home="Юность", away="Шахтер")
    assert await ev.produce_comeback(db_session, now=WED) == []  # дальше шести суток
    near = await seed_match(db_session, at(19, day=16), home="Юность", away="Шахтер")
    assert len(await ev.produce_comeback(db_session, now=WED)) == 1
    await seed_pick(db_session, SASHA, at(9, day=11), match_id=near)
    assert far and await ev.produce_comeback(db_session, now=WED) == []


@pytest.mark.asyncio
async def test_comeback_attempts_per_silence_and_reset_by_pick(db_session) -> None:
    await active_player(db_session, days_ago=10)
    await seed_match(db_session, at(19, day=13), home="Юность", away="Шахтер")
    last = at(10, day=1)
    assert len(await ev.produce_comeback(db_session, now=WED)) == 1  # ступень 2 (10 суток), попыток не было
    await seed_notice(db_session, SASHA, "comeback", WED - timedelta(days=7))  # ступень 1 уже была
    assert len(await ev.produce_comeback(db_session, now=WED)) == 1
    await seed_notice(db_session, SASHA, "comeback", WED - timedelta(days=1))  # и ступень 2
    assert await ev.produce_comeback(db_session, now=WED) == []  # на этой ступени уже писали
    assert last


@pytest.mark.asyncio
async def test_comeback_ignores_attempts_before_the_last_pick(db_session) -> None:
    await active_player(db_session, days_ago=3)
    await seed_match(db_session, at(19, day=13), home="Юность", away="Шахтер")
    for days in (40, 30, 20):  # три старые попытки прошлого молчания
        await seed_notice(db_session, SASHA, "comeback", WED - timedelta(days=days))
    assert len(await ev.produce_comeback(db_session, now=WED)) == 1  # ход обнулил счётчик


@pytest.mark.asyncio
async def test_comeback_nothing_after_thirty_days_or_between_steps(db_session) -> None:
    await active_player(db_session, days_ago=31)
    await seed_match(db_session, at(19, day=13), home="Юность", away="Шахтер")
    assert await ev.produce_comeback(db_session, now=WED) == []
    await active_player(db_session, KATYA, days_ago=2)
    assert KATYA not in [p.notice.player_key for p in await ev.produce_comeback(db_session, now=WED)]


@pytest.mark.asyncio
async def test_comeback_thirty_day_step_uses_date_wording(db_session) -> None:
    await active_player(db_session, days_ago=30)
    await seed_match(db_session, at(19, 30, day=11) + timedelta(days=5), home="Юность", away="Шахтер")
    [p] = await ev.produce_comeback(db_session, now=WED)
    assert "в~понедельник" in plain(p.notice.text)  # 16 ноября — понедельник, пять суток от среды
    # дата словом — если матч дальше шести суток от момента отправки
    assert tx.day_phrase(at(19, 30, day=3, month=12), WED) == "3 декабря"


async def _month_table(db, *, me_points: int, others: list[int], me=SASHA, club="Динамо-Минск"):
    """Ноябрьская таблица клуба: матчи сыграны, очки заданы. Возвращает ключи остальных игроков."""
    keys = []
    mid = await seed_final(db, club, "Спартак", at(19, day=3))
    await seed_player(db, me, registered=REG, notify_consent=True)
    await seed_scored(db, me, mid, me_points)
    for i, pts in enumerate(others):
        key = 9430000 + i
        await seed_player(db, key, registered=REG)
        await seed_scored(db, key, mid, pts)
        keys.append(key)
    return mid, keys


@pytest.mark.asyncio
async def test_comeback_ten_day_step_names_place_by_rule(db_session) -> None:
    mid, _ = await _month_table(db_session, me_points=30, others=[50, 50, 30, 20, 10])  # я: 3-й из 6
    # игрок 10 суток молчит; «своя» команда — Динамо-Минск, по ходу 3 ноября
    await db_session.execute(text("UPDATE hockey_picks SET picked_at = :t WHERE player_key = :k"), {"t": at(10, day=1), "k": SASHA})
    await seed_match(db_session, at(19, day=13), home="Динамо-Минск", away="Спартак")
    [p] = [x for x in await ev.produce_comeback(db_session, now=WED) if x.notice.player_key == SASHA]
    assert plain(p.notice.text).splitlines()[0] == "В~таблице ноября (Динамо-Минск) ты на~3-м~месте."
    assert mid


@pytest.mark.asyncio
async def test_comeback_ten_day_step_no_place_in_bottom_half_or_small_table(db_session) -> None:
    await _month_table(db_session, me_points=10, others=[50, 50, 30, 20, 20])  # я: последний из 6
    await db_session.execute(text("UPDATE hockey_picks SET picked_at = :t WHERE player_key = :k"), {"t": at(10, day=1), "k": SASHA})
    await seed_match(db_session, at(19, day=13), home="Динамо-Минск", away="Спартак")
    [p] = [x for x in await ev.produce_comeback(db_session, now=WED) if x.notice.player_key == SASHA]
    assert len(p.notice.text.splitlines()) == 1  # только строка матча


# ---------- 3. итог недели ----------

MON = at(10, 0, day=16)


async def _week_world(db, *, points=(30, 30, 0)):
    """Неделя 9–15 ноября: три сыгранных матча «Юности»; Саша ходил на все."""
    await seed_player(db, SASHA, registered=REG, notify_consent=True)
    ids = []
    for i, pts in enumerate(points):
        mid = await seed_final(db, "Юность", "Шахтер", at(19, day=9 + i * 2))
        await seed_scored(db, SASHA, mid, pts)
        ids.append(mid)
    return ids


@pytest.mark.asyncio
async def test_week_text_with_place_and_match_line(db_session) -> None:
    ids = await _week_world(db_session)
    for i, pts in enumerate([50, 50, 10, 10, 0]):  # ещё пятеро в таблице клуба
        key = 9431000 + i
        await seed_player(db_session, key, registered=REG)
        await seed_scored(db_session, key, ids[0], pts)
    await seed_match(db_session, at(19, 30, day=18), home="Юность", away="Шахтер")
    [p] = await ev.produce_week(db_session, now=MON)
    lines = plain(p.notice.text).splitlines()
    assert lines[0] == "За~неделю 3~хода и~60~очков, в~таблице ноября (Юность) ты на~1-м~месте."
    assert lines[1] == "<b>Юность~— Шахтёр</b> в~среду в~19:30. Твой ход?"
    assert p.notice.kind == "week" and p.notice.match_id == ids[-1]  # якорь — последний матч недели


@pytest.mark.asyncio
async def test_week_no_place_when_table_small_and_no_line_when_picked(db_session) -> None:
    await _week_world(db_session)
    nxt = await seed_match(db_session, at(19, day=18), home="Юность", away="Шахтер")
    await seed_pick(db_session, SASHA, at(9, day=16), match_id=nxt)
    [p] = await ev.produce_week(db_session, now=MON)
    assert plain(p.notice.text) == "За~неделю 3~хода и~60~очков."  # участников меньше пяти, матч с ходом


@pytest.mark.asyncio
async def test_week_conditions(db_session) -> None:
    await _week_world(db_session, points=(0, 0))
    assert await ev.produce_week(db_session, now=MON) == []  # очков за неделю нет
    assert await ev.produce_week(db_session, now=at(10, day=17)) == []  # не понедельник


@pytest.mark.asyncio
async def test_week_not_on_first_of_month_monday(db_session) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1, month=1, year=2027), notify_consent=True)
    mid = await seed_final(db_session, "Юность", "Шахтер", at(19, day=27, month=1, year=2027))
    await seed_scored(db_session, SASHA, mid, 30)
    feb1 = at(10, 0, day=1, month=2, year=2027)  # понедельник, 1-е число
    assert await ev.produce_week(db_session, now=feb1) == []


@pytest.mark.asyncio
async def test_week_window_and_phase(db_session) -> None:
    await _week_world(db_session)
    assert await ev.produce_week(db_session, now=at(8, 59, day=16)) == []
    assert await ev.produce_week(db_session, now=at(11, 0, day=16)) == []
    # неактивный (последний ход 20 дней назад) итог недели не получает
    await db_session.execute(text("UPDATE hockey_picks SET picked_at = :t WHERE player_key = :k"), {"t": at(10, day=1), "k": SASHA})
    assert await ev.produce_week(db_session, now=MON) == []


# ---------- 4. итог месяца ----------

DEC1 = at(10, 0, day=1, month=12)


async def _close_november(db, club="Динамо-Минск", crowned: list[int] | None = None):
    await db.execute(
        text("INSERT INTO hockey_closures (kind, period_start, club, crowned) VALUES ('month', :s, :c, :n)"),
        {"s": at(0, day=1), "c": club, "n": len(crowned or [])},
    )
    for key in crowned or []:
        await db.execute(
            text("""INSERT INTO hockey_crowns (player_key, points, exact, kind, club, period_start, period_end)
                    VALUES (:k, 100, 1, 'month', :c, :s, :e)"""),
            {"k": key, "c": club, "s": at(0, day=1), "e": at(0, day=1, month=12)},
        )


@pytest.mark.asyncio
async def test_month_without_crown_with_place(db_session) -> None:
    await _month_table(db_session, me_points=30, others=[50, 50, 30, 20, 10])
    await _close_november(db_session)
    [p] = [x for x in await ev.produce_month(db_session, now=DEC1) if x.notice.player_key == SASHA]
    assert plain(p.notice.text) == "В~таблице ноября (Динамо-Минск) ты на~3-м~месте из~6: 30~очков."
    assert p.notice.kind == "month"


@pytest.mark.asyncio
async def test_month_crown_variants(db_session) -> None:
    mid, others = await _month_table(db_session, me_points=50, others=[50, 50, 10, 10, 0])
    await db_session.execute(text("UPDATE hockey_picks SET points = 50 WHERE match_id = :m AND player_key = :k"), {"m": mid, "k": SASHA})
    for crowned, expected in (
        ([SASHA], "Корона за~ноябрь (Динамо-Минск)~— твоя. 50~очков, 1~ход в~точку."),
        ([SASHA, others[0]], "Корона за~ноябрь (Динамо-Минск)~— на~двоих: у~тебя и~ещё одного игрока."),
        ([SASHA, others[0], others[1]], "Корона за~ноябрь (Динамо-Минск)~— общая: у~тебя и~ещё 2~игрока."),
    ):
        await db_session.execute(text("DELETE FROM hockey_closures"))
        await db_session.execute(text("DELETE FROM hockey_crowns"))
        await _close_november(db_session, crowned=crowned)
        [p] = [x for x in await ev.produce_month(db_session, now=DEC1) if x.notice.player_key == SASHA]
        assert plain(p.notice.text) == expected


@pytest.mark.asyncio
async def test_month_conditions(db_session) -> None:
    await _month_table(db_session, me_points=30, others=[50, 50, 30, 20, 10])
    assert await ev.produce_month(db_session, now=DEC1) == []  # месяц не закрыт
    await _close_november(db_session)
    assert len(await ev.produce_month(db_session, now=DEC1)) >= 1
    assert await ev.produce_month(db_session, now=at(9, 59, day=1, month=12)) == []  # раньше 10:00
    assert await ev.produce_month(db_session, now=at(10, 0, day=2, month=12)) == []  # не первое число
    await seed_final(db_session, "Динамо-Минск", "Спартак", at(20, day=30), status="scheduled")
    assert await ev.produce_month(db_session, now=DEC1) == []  # есть неподтверждённый матч месяца
    await db_session.execute(text("DELETE FROM hockey_matches WHERE status = 'scheduled' AND starts_at < :t"), {"t": at(0, day=1, month=12)})
    assert len(await ev.produce_month(db_session, now=DEC1)) >= 1
    mid = await seed_final(db_session, "Динамо-Минск", "Спартак", at(20, day=29))
    await seed_notice(db_session, SASHA, "rescore", None, created_at=at(9, day=30))
    assert mid and await ev.produce_month(db_session, now=DEC1) == []  # итог на правке


@pytest.mark.asyncio
async def test_month_requires_scored_points(db_session) -> None:
    await _month_table(db_session, me_points=0, others=[50, 50, 30, 20, 10])
    await _close_november(db_session)
    assert SASHA not in [x.notice.player_key for x in await ev.produce_month(db_session, now=DEC1)]


@pytest.mark.asyncio
async def test_month_recheck_stops_when_month_reopened(db_session, factory) -> None:
    await _month_table(db_session, me_points=30, others=[50, 50, 30, 20, 10])
    await _close_november(db_session)
    [p] = [x for x in await ev.produce_month(db_session, now=DEC1) if x.notice.player_key == SASHA]
    await seed_notice(db_session, SASHA, "rescore", None, created_at=at(9, day=1, month=12))  # правку поставили позже
    out = Outbox()
    r = await dispatch(factory, p, phase="active", tick_at=DEC1, send=out, config=CFG, clock=lambda: DEC1)
    assert r.reason == "stale:month_not_closed" and out.sent == []


# ---------- 5. согласие после первого хода ----------


@pytest.mark.asyncio
async def test_consent_message_after_first_pick(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG)
    mid = await seed_pick(db_session, SASHA, at(9, day=11))
    [p] = await ev.produce_consent(db_session, now=WED)
    assert p.notice.kind == "consent" and p.notice.match_id == mid
    assert plain(p.notice.text) == "Присылать напоминания о~матчах и~итоги недели и~месяца? Не~чаще раза в~день."
    assert [(b["text"], b["callback_data"]) for b in p.notice.buttons[0]] == [("Присылать", "kk:yes"), ("Не присылать", "kk:noall")]


@pytest.mark.asyncio
async def test_consent_only_for_unasked_players_with_picks(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    await seed_pick(db_session, SASHA, at(9, day=11))
    await seed_player(db_session, KATYA, registered=REG)  # без ходов
    await seed_player(db_session, LESHA, registered=REG, remind=False)
    await seed_pick(db_session, LESHA, at(9, day=11))
    assert await ev.produce_consent(db_session, now=WED) == []


@pytest.mark.asyncio
async def test_consent_gate_rules(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG)  # согласия нет
    for kind in ("invite", "comeback", "week", "month"):
        assert (await admit(db_session, kind=kind, player_key=SASHA, now=at(10), config=CFG)).reason == gate.NO_CONSENT
    assert (await admit(db_session, kind="consent", player_key=SASHA, now=at(10), config=CFG)).allowed
    await seed_player(db_session, KATYA, registered=REG, notify_consent=False)
    assert (await admit(db_session, kind="invite", player_key=KATYA, now=at(10), config=CFG)).reason == gate.NO_CONSENT
    await seed_player(db_session, LESHA, registered=REG, notify_consent=True)
    assert (await admit(db_session, kind="invite", player_key=LESHA, now=at(10), config=CFG)).allowed


@pytest.mark.asyncio
async def test_consent_false_means_phase_off_until_player_returns(db_session) -> None:
    await active_player(db_session, consent=False)
    facts = await load_one(db_session, SASHA, as_of=WED)
    assert facts.phase(WED) is Phase.OFF
    await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    for produce in (ev.produce_invite, ev.produce_comeback, ev.produce_week, ev.produce_month, ev.produce_consent):
        assert await produce(db_session, now=WED) == []
    await hn.set_consent(db_session, SASHA, True)  # вернулся сам («Присылать»)
    assert len(await ev.produce_invite(db_session, now=WED)) == 1


@pytest.mark.asyncio
async def test_do_not_send_switches_off_new_kinds_but_not_results(db_session) -> None:
    await active_player(db_session)
    await hn.set_consent(db_session, SASHA, False)
    for kind in ("invite", "comeback", "week", "month"):
        assert (await admit(db_session, kind=kind, player_key=SASHA, now=at(10), config=CFG)).reason == gate.NO_CONSENT
    for kind in ("result", "moved", "rescore"):
        assert (await admit(db_session, kind=kind, player_key=SASHA, now=at(12))).allowed  # итоги и события — как раньше


# ---------- пауза «два приглашения без хода» ----------


@pytest.mark.asyncio
async def test_pause_after_two_silent_invites(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    await seed_notice(db_session, SASHA, "invite", WED - timedelta(days=3))
    await seed_notice(db_session, SASHA, "comeback", WED - timedelta(days=2))
    assert await ev.apply_silence_pause(db_session, now=WED) == 1
    paused = (await db_session.execute(text("SELECT notify_paused_until FROM hockey_player_prefs WHERE player_key = :k"), {"k": SASHA})).scalar_one()
    assert paused == WED + timedelta(days=30)
    assert (await admit(db_session, kind="invite", player_key=SASHA, now=WED + timedelta(days=29), config=CFG)).reason == gate.PAUSED
    assert await ev.apply_silence_pause(db_session, now=WED) == 0  # уже на паузе


@pytest.mark.asyncio
async def test_pause_not_set_when_a_pick_followed_or_invite_too_fresh(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    sent1, sent2 = WED - timedelta(days=3), WED - timedelta(days=2)
    await seed_notice(db_session, SASHA, "invite", sent1)
    await seed_notice(db_session, SASHA, "invite", sent2)
    await seed_pick(db_session, SASHA, sent2 + timedelta(hours=23, minutes=59))  # ход в пределах суток
    assert await ev.apply_silence_pause(db_session, now=WED) == 0
    await seed_player(db_session, KATYA, registered=REG, notify_consent=True)
    await seed_notice(db_session, KATYA, "invite", WED - timedelta(days=3))
    await seed_notice(db_session, KATYA, "invite", WED - timedelta(hours=23, minutes=59))  # ещё не созрело
    assert await ev.apply_silence_pause(db_session, now=WED) == 0


@pytest.mark.asyncio
async def test_pause_pick_after_a_day_does_not_save_the_player(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    s1, s2 = WED - timedelta(days=4), WED - timedelta(days=3)
    await seed_notice(db_session, SASHA, "invite", s1)
    await seed_notice(db_session, SASHA, "invite", s2)
    await seed_pick(db_session, SASHA, s2 + timedelta(hours=24, minutes=1))  # позже суток
    assert await ev.apply_silence_pause(db_session, now=WED) == 1


@pytest.mark.asyncio
async def test_old_invites_before_finished_pause_do_not_repause(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    await seed_notice(db_session, SASHA, "invite", WED - timedelta(days=40))
    await seed_notice(db_session, SASHA, "invite", WED - timedelta(days=38))
    await db_session.execute(text("UPDATE hockey_player_prefs SET notify_paused_until = :t WHERE player_key = :k"), {"t": WED - timedelta(days=5), "k": SASHA})
    assert await ev.apply_silence_pause(db_session, now=WED) == 0  # пауза кончилась, приглашения были до неё


# ---------- сквозной проход run_tick ----------


@pytest.mark.asyncio
async def test_tick_end_to_end_sends_one_message_per_day(db_session, factory) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    out = Outbox()
    counts = await run_tick(factory, now=WED, send=out, config=CFG, clock=lambda: WED)
    assert counts == {"ok": 1} and [t for _, t, _ in out.sent] == [plain_to_real(out.sent[0][1])]
    assert "Юность" in out.sent[0][1] and "сегодня" in out.sent[0][1]
    again = await run_tick(factory, now=WED + timedelta(minutes=10), send=out, config=CFG, clock=lambda: WED + timedelta(minutes=10))
    assert len(out.sent) == 1 and again.get("skip") == 1  # второй проход за день — дневной лимит


def plain_to_real(value: str) -> str:
    return value


@pytest.mark.asyncio
async def test_tick_dry_run_journals_without_sending(db_session, factory) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(19, day=11), home="Юность", away="Шахтер")
    cfg = GateConfig(enabled=True, dry_run=True, texts_accepted=False, kinds=ALL_KINDS)
    out = Outbox()
    counts = await run_tick(factory, now=WED, send=out, config=cfg, clock=lambda: WED)
    assert out.sent == [] and counts == {"dry_run": 1}
    rows = (await db_session.execute(text("SELECT kind, decision, reason FROM kk_notify_decisions"))).all()
    assert [tuple(r) for r in rows] == [("invite", "dry_run", "dry_run")]


@pytest.mark.asyncio
async def test_tick_priority_week_beats_invite(db_session, factory) -> None:
    ids = await _week_world(db_session)
    old = await seed_match(db_session, MON - timedelta(days=2), home="Юность", away="Неман")
    await seed_pick(db_session, SASHA, MON - timedelta(days=1), match_id=old)
    await seed_match(db_session, at(19, day=16), home="Юность", away="Шахтер")  # матч сегодня — тоже повод
    out = Outbox()
    await run_tick(factory, now=MON, send=out, config=CFG, clock=lambda: MON)
    assert len(out.sent) == 1 and out.sent[0][1].startswith("За") and ids


@pytest.mark.asyncio
async def test_new_kinds_are_registered_with_limits() -> None:
    for kind in ALL_KINDS:
        policy = gate.KIND_POLICY[kind]
        assert policy.new and policy.budgeted and policy.weekly
        assert policy.needs_consent == (kind != "consent")
        assert len(kind) <= 12


@pytest.mark.asyncio
async def test_comeback_place_line_only_on_ten_day_step(db_session) -> None:
    await _month_table(db_session, me_points=30, others=[50, 50, 30, 20, 10])  # место есть
    await seed_match(db_session, at(19, day=13), home="Динамо-Минск", away="Спартак")
    for days_ago in (3, 30):
        await db_session.execute(text("UPDATE hockey_picks SET picked_at = :t WHERE player_key = :k"), {"t": WED - timedelta(days=days_ago), "k": SASHA})
        [p] = [x for x in await ev.produce_comeback(db_session, now=WED) if x.notice.player_key == SASHA]
        assert len(p.notice.text.splitlines()) == 1, days_ago


@pytest.mark.asyncio
async def test_pause_judges_invites_older_than_a_day_and_needs_two(db_session) -> None:
    await seed_player(db_session, SASHA, registered=REG, notify_consent=True)
    await seed_notice(db_session, SASHA, "invite", WED - timedelta(days=3))
    await seed_notice(db_session, SASHA, "invite", WED - timedelta(hours=24, minutes=1))  # уже созрело
    assert await ev.apply_silence_pause(db_session, now=WED) == 1
    await seed_player(db_session, KATYA, registered=REG, notify_consent=True)
    await seed_notice(db_session, KATYA, "invite", WED - timedelta(days=3))  # одно приглашение — мало
    assert await ev.apply_silence_pause(db_session, now=WED) == 0


@pytest.mark.asyncio
async def test_text_is_rendered_at_send_time_not_build_time(db_session, factory) -> None:
    await active_player(db_session)
    await seed_match(db_session, at(17, day=12), home="Юность", away="Шахтер")
    [p] = await ev.produce_invite(db_session, now=WED)
    assert "завтра" in p.notice.text
    out = Outbox()
    later = at(10, 0, day=12)  # отправка на следующие сутки: матч уже «сегодня»
    r = await dispatch(factory, p, phase="active", tick_at=WED, send=out, config=CFG, clock=lambda: later)
    assert r.decision == "send" and "сегодня" in out.sent[0][1] and "завтра" not in out.sent[0][1]


@pytest.mark.asyncio
async def test_comeback_and_week_text_rendered_at_send_time(db_session) -> None:
    await active_player(db_session, days_ago=3)
    await seed_match(db_session, at(19, day=12), home="Юность", away="Шахтер")
    [c] = await ev.produce_comeback(db_session, now=WED)
    assert "завтра" in c.notice.text and "сегодня" in c.render(at(10, 0, day=12))
    ids = await _week_world(db_session)
    await seed_match(db_session, at(19, day=17), home="Юность", away="Неман")
    [w] = [x for x in await ev.produce_week(db_session, now=MON) if x.notice.player_key == SASHA]
    assert "завтра" in w.notice.text and "сегодня" in w.render(at(10, 0, day=17)) and ids
