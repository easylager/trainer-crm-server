"""Право капитана по живой базе (TASK-432): кто выдаёт, что видно в лиге и снаружи, когда выдача снимается."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.hockey_league_captain import (
    AlreadyGiven,
    NotCaptain,
    OutfitRefused,
    RightClosed,
    current_state,
    outside_outfits,
    set_outfit,
)
from src.application.hockey_league_evening import game_day
from src.application.hockey_leagues import member_league
from tests.application.test_hockey_league_evening import ANYA, LATE, ME, NOW, SASHA, _evening, _league, _match, _pick


@pytest.fixture(autouse=True)
def _captain_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Право капитана включено во всех лигах (KK_CAPTAIN_LEAGUES=*); тесты выключения ставят своё."""
    monkeypatch.setenv("KK_CAPTAIN_LEAGUES", "*")


D1 = NOW - timedelta(days=2)


async def _pid(db, key: int) -> str:
    return (
        await db.execute(text("SELECT public_id FROM hockey_players WHERE player_key = :k"), {"k": key})
    ).scalar_one()


async def _played_day(db, league_id: int, at: datetime, points: dict[int, tuple[int, int]]) -> date:
    """Вечер из двух сыгранных матчей; ``points`` — очки каждого за оба матча."""
    a = await _match(db, "Юность-Минск", "Неман", at, score=(2, 1))
    b = await _match(db, "Гомель", "Шахтёр", at + timedelta(hours=1), score=(1, 4))
    for key, pts in points.items():
        await _pick(db, key, a, "home", points=pts[0])
        await _pick(db, key, b, "home", points=pts[1])
    return game_day(at)


async def _give(db, league_id: int, captain: int, to: int, item: str, day: date, *, now: datetime = NOW) -> None:
    league = await member_league(db, league_id=league_id, player_key=captain)
    await set_outfit(db, league=league, captain_key=captain, to_pid=await _pid(db, to), item=item, day=day, now=now)


BASIC = {ME: (50, 20), ANYA: (20, 20), SASHA: (0, 0)}  # Макс — капитан, Саша — в кепке


@pytest.mark.asyncio
async def test_captain_gives_anyone_even_self_and_can_change(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)

    ev = await _evening(db, league_id, day=day)
    assert ev["captain_on"] and ev["captain"]["right"] is True and ev["captain"]["award"] is None
    # Подсказка: тот, кто в кепке, и вещь по его вечеру (0 угаданных — плакат).
    assert ev["captain"]["suggest"] == {"to": await _pid(db, SASHA), "item": "wanted", "revenge": None}
    by = {r["display_name"]: r for r in ev["items"]}
    assert by["Макс"]["captain"] and by["Саша"]["head"] == {"item": "cap"} and by["Аня"]["head"] is None

    await _give(db, league_id, ME, SASHA, "wanted", day)
    ev = await _evening(db, league_id, day=day)
    sasha = next(r for r in ev["items"] if r["display_name"] == "Саша")
    # Плакат берёт цифры из вечера получателя: 0 угаданных из 2, первый промах — 2:1.
    assert sasha["head"] == {"item": "wanted", "stat": "ЗА 0 ИЗ 2", "score": "2:1"}
    assert ev["captain"]["award"]["from_me"] and ev["captain"]["award"]["to"] == sasha["pid"]

    await _give(db, league_id, ME, ME, "foil", day)  # себе — можно, и поменять — тоже
    ev = await _evening(db, league_id, day=day)
    by = {r["display_name"]: r for r in ev["items"]}
    assert by["Макс"]["head"]["item"] == "foil" and by["Саша"]["head"] == {"item": "cap"}

    theirs = await _evening(db, league_id, day=day, me=ANYA)
    assert theirs["captain"]["right"] is False and theirs["captain"]["award"]["from"] == "Макс"

    with pytest.raises(NotCaptain):
        await _give(db, league_id, ANYA, SASHA, "bag", day)
    with pytest.raises(OutfitRefused):
        await _give(db, league_id, ME, SASHA, "scarf", day)  # шарф соперника не выдаётся
    with pytest.raises(OutfitRefused):
        league = await member_league(db, league_id=league_id, player_key=ME)
        await set_outfit(db, league=league, captain_key=ME, to_pid="nobody", item="bag", day=day, now=NOW)


@pytest.mark.asyncio
async def test_next_played_evening_takes_the_outfit_off(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    await _give(db, league_id, ME, SASHA, "bucket", day)
    league = await member_league(db, league_id=league_id, player_key=ME)
    assert (await current_state(db, league, now=NOW)).head(SASHA, enabled=True)["item"] == "bucket"
    assert (await outside_outfits(db, [SASHA], now=NOW))[SASHA]["item"] == "bucket"

    # Новый вечер сыгран: капитан теперь Аня, старая выдача не действует и поменять её нельзя.
    today = await _played_day(db, league_id, NOW - timedelta(hours=4), {ME: (0, 0), ANYA: (50, 50), SASHA: (20, 0)})
    state = await current_state(db, league, now=NOW)
    assert state.day == today and state.cap.captains == {ANYA} and state.head(SASHA, enabled=True) is None
    assert await outside_outfits(db, [SASHA], now=NOW) == {}
    old = await _evening(db, league_id, day=day)
    assert old["captain"]["right"] is False and old["captain"]["award"]["current"] is False
    with pytest.raises(RightClosed):
        await _give(db, league_id, ME, ANYA, "bag", day)


@pytest.mark.asyncio
async def test_corrected_result_moves_the_right_to_the_new_captain(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    await _give(db, league_id, ME, SASHA, "bag", day)
    # Итог поправили: у Ани стало больше всех — выдача Макса снимается, право у Ани.
    await db.execute(text("UPDATE hockey_picks SET points = 50 WHERE player_key = :k"), {"k": ANYA})
    ev = await _evening(db, league_id, day=day, me=ANYA)
    assert ev["captain"]["right"] is True and ev["captain"]["award"] is None
    assert next(r for r in ev["items"] if r["display_name"] == "Саша")["head"] == {"item": "cap"}
    await _give(db, league_id, ANYA, SASHA, "sieve", day)
    assert (await _evening(db, league_id, day=day))["captain"]["award"]["from"] == "Аня"


@pytest.mark.asyncio
async def test_co_captains_first_one_gives(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, {ME: (50, 20), ANYA: (20, 50), SASHA: (0, 0)})
    await _give(db, league_id, ANYA, SASHA, "snorkel", day)
    assert (await _evening(db, league_id, day=day))["captain"]["right"] is False
    with pytest.raises(AlreadyGiven) as err:
        await _give(db, league_id, ME, SASHA, "bag", day)
    assert err.value.name == "Аня"


@pytest.mark.asyncio
async def test_recipient_who_left_wears_nothing(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga", members=(ME, ANYA, SASHA, LATE))
    await db.execute(
        text("UPDATE hockey_league_members SET joined_at = :j WHERE league_id = :l"),
        {"j": D1 - timedelta(days=1), "l": league_id},
    )
    day = await _played_day(db, league_id, D1, {**BASIC, LATE: (20, 0)})
    await _give(db, league_id, ME, LATE, "curlers", day)
    await db.execute(
        text("DELETE FROM hockey_league_members WHERE league_id = :l AND player_key = :k"), {"l": league_id, "k": LATE}
    )
    ev = await _evening(db, league_id, day=day)
    assert ev["captain"]["award"] is None and ev["captain"]["right"] is True
    assert await outside_outfits(db, [LATE], now=NOW) == {}


@pytest.mark.asyncio
async def test_outside_shows_the_last_given_and_the_list_from_all_leagues(db_session) -> None:
    db = db_session
    work = await _league(db, scope="extraliga")
    yard = await _league(db, scope="extraliga")
    d_work = await _played_day(db, work, D1, BASIC)
    # Во второй лиге матчи те же: вечер тот же, капитан тот же, кепка у Саши.
    await _give(db, work, ME, SASHA, "bucket", d_work)
    await _give(db, yard, ME, SASHA, "wanted", d_work)
    found = await outside_outfits(db, [SASHA, ANYA], now=NOW)
    assert set(found) == {SASHA}
    assert found[SASHA]["item"] == "wanted"  # последняя выданная
    assert [(x["item"], x["n"]) for x in found[SASHA]["items"]] == [("wanted", 1), ("bucket", 1)]
    assert found[SASHA]["items"][0]["stat"] == "ЗА 0 ИЗ 2"

    await _give(db, work, ME, SASHA, "wanted", d_work)  # одна вещь из двух лиг — вместе
    assert [(x["item"], x["n"]) for x in (await outside_outfits(db, [SASHA], now=NOW))[SASHA]["items"]] == [
        ("wanted", 2)
    ]


@pytest.mark.asyncio
async def test_switched_off_hides_outfits_but_keeps_cap_and_captain(db_session, monkeypatch) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    await _give(db, league_id, ME, ANYA, "hardhat", day)
    monkeypatch.setenv("KK_CAPTAIN_LEAGUES", "")
    ev = await _evening(db, league_id, day=day)
    by = {r["display_name"]: r for r in ev["items"]}
    assert ev["captain"]["right"] is False and ev["captain"]["award"] is None and by["Макс"]["captain"]
    assert by["Аня"]["head"] is None and by["Саша"]["head"] == {"item": "cap"}
    assert await outside_outfits(db, [ANYA], now=NOW) == {}


@pytest.mark.asyncio
async def test_simultaneous_co_captains_do_not_overwrite_each_other(db_session) -> None:
    """Оба прочли «выдачи нет»: запись второго не затирает выдачу первого, пока тот ещё капитан."""
    from src.application.hockey_league_captain import _UPSERT, day_award

    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, {ME: (50, 20), ANYA: (20, 50), SASHA: (0, 0)})
    await _give(db, league_id, ANYA, SASHA, "snorkel", day)
    params = {"league_id": league_id, "day": day, "to_key": SASHA, "item": "bag", "captains": [ME, ANYA]}
    assert (await db.execute(_UPSERT, {**params, "captain_key": ME})).scalar_one_or_none() is None
    assert (await day_award(db, league_id, day)).item == "snorkel"
    # Выдавший больше не капитан — его выдачу перезаписать можно.
    assert (await db.execute(_UPSERT, {**params, "captain_key": ME, "captains": [ME]})).scalar_one() == ME


@pytest.mark.asyncio
async def test_digest_invites_only_captains_whose_right_is_open(db_session) -> None:
    from src.application.hockey_league_evening import _open_captains, cap_of_rows, day_matches, day_rows, league_members

    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, {ME: (50, 20), ANYA: (20, 50), SASHA: (0, 0)})
    league = await member_league(db, league_id=league_id, player_key=ME)
    ms = await day_matches(db, league, day)
    cap = cap_of_rows(await day_rows(db, league_id, await league_members(db, league_id, now=NOW), ms), ms)
    assert await _open_captains(db, league, day, cap, NOW) == {ME, ANYA}
    await _give(db, league_id, ANYA, SASHA, "bag", day)
    assert await _open_captains(db, league, day, cap, NOW) == frozenset()  # уже выдано — звать некого
    assert await _open_captains(db, league, day, cap, league.ends_at + timedelta(hours=1)) == frozenset()


@pytest.mark.asyncio
async def test_revenge_suggests_returning_the_same_item(db_session) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    d1 = await _played_day(db, league_id, D1, {ANYA: (50, 50), SASHA: (20, 20), ME: (0, 0)})
    await _give(db, league_id, ANYA, ME, "bucket", d1)
    today = await _played_day(db, league_id, NOW - timedelta(hours=4), {ME: (50, 50), ANYA: (20, 0), SASHA: (0, 0)})
    ev = await _evening(db, league_id, day=today)
    assert ev["captain"]["right"] is True
    assert ev["captain"]["suggest"] == {"to": await _pid(db, ANYA), "item": "bucket", "revenge": "bucket"}


def test_suggested_item_follows_the_evening() -> None:
    from src.application.hockey_league_captain import suggest_item
    from src.application.hockey_league_evening import DayMatch, DayRow, Member

    ms = [DayMatch(1, "А", "Б", NOW, "final", 2, 1), DayMatch(2, "В", "Г", NOW, "final", 0, 3)]
    member = Member(1, "Олег", "p1", NOW)

    def row(*points):
        picks = {m.id: {"points": p, "doubled": False, "final": True} for m, p in zip(ms, points) if p is not None}
        return DayRow(member=member, picks=picks)

    assert suggest_item(row(None, None), ms) == "snorkel"
    assert suggest_item(row(0, 0), ms) == "wanted"
    assert suggest_item(row(20, 0), ms) == "scorehat"
    assert suggest_item(row(20, 50), ms) == "bucket"


def test_captain_line_offers_one_tap_without_declining_names() -> None:
    from src.application.hockey_notices import captain_line, offer_button

    offer = {"pid": "p1", "name": "Олег", "me": False, "item": "wanted", "hits": 0, "matches": 4, "revenge": False}
    assert captain_line(league_name="Работа", offer=offer) == (
        "<b>Ты капитан</b> в лиге «Работа». Олег — 0 из 4: выдать плакат? Или выбери другое в «Вечере»."
    )
    revenge = {**offer, "item": "bucket", "revenge": True}
    assert captain_line(league_name="Работа", offer=revenge) == (
        "<b>Ты капитан</b> в лиге «Работа». Олег — автор твоего ведра. Самое время вернуть — или выбери другое в «Вечере»."
    )
    assert offer_button(7, date(2026, 11, 16), revenge) == {
        "text": "Вернуть ведро",
        "callback_data": "kk:o:7:261116:p1:bucket",
    }
    assert (
        len(offer_button(123456, date(2026, 11, 16), {**offer, "pid": "x" * 12, "item": "scorehat"})["callback_data"])
        <= 64
    )
    assert offer_button(7, date(2026, 11, 16), {**offer, "me": True})["text"] == "Выдать себе плакат"


def test_outfit_words_agree_in_gender_and_case() -> None:
    """Род у вещей разный: «автор твоей каски», «твоих бигудей»; бигуди во множественном — «в бигудях»."""
    from src.application.hockey_league_captain import OUTFIT_PHRASES, OUTFIT_WORDS
    from src.application.hockey_notices import captain_line

    offer = {"pid": "p1", "name": "Олег", "me": False, "item": "hardhat", "hits": 0, "matches": 4, "revenge": True}
    assert "Олег — автор твоей каски." in captain_line(league_name="Работа", offer=offer)
    assert OUTFIT_WORDS["curlers"][2] == "твоих бигудей"
    assert OUTFIT_WORDS["snorkel"][2] == "твоей маски с трубкой"
    assert OUTFIT_PHRASES["curlers"] == "в бигудях"
    assert all(w[2].startswith(("твоего ", "твоей ", "твоих ")) for w in OUTFIT_WORDS.values())


@pytest.mark.asyncio
async def test_given_from_chat_and_the_recipient_gets_one_message(db_session) -> None:
    from contextlib import asynccontextmanager

    from src.application import hockey_notices
    from src.application.hockey_league_captain import chat_give

    hockey_notices._RETRIES.clear()
    db = db_session

    @asynccontextmanager
    async def factory():
        yield db

    sent: list[tuple[int, str, list]] = []

    async def send(chat_id: int, body: str, buttons) -> str:
        sent.append((chat_id, body, buttons))
        return hockey_notices.SENT

    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    got = await chat_give(
        db, league_id=league_id, captain_key=ME, day=day, to_pid=await _pid(db, SASHA), item="wanted", now=NOW
    )
    assert got == ("Саша", False)
    await hockey_notices.deliver_outfit_notices(factory, now=NOW, send=send)
    assert [(k, b.split("</b>")[0]) for k, b, _ in sent] == [(SASHA, "<b>Макс выдаёт тебе экипировку")]
    assert "плакат «Разыскивается» — до следующего вечера" in sent[0][1]
    assert [b["callback_data"] for row in sent[0][2] for b in row if "callback_data" in b] == ["kk:off:of"]

    await _give(db, league_id, ME, SASHA, "bag", day)  # тому же — другая вещь: второе сообщение не шлём
    await hockey_notices.deliver_outfit_notices(factory, now=NOW, send=send)
    assert len(sent) == 1
    await _give(db, league_id, ME, ANYA, "bag", day)  # новый получатель — новое сообщение
    await hockey_notices.deliver_outfit_notices(factory, now=NOW, send=send)
    assert [k for k, _, _ in sent] == [SASHA, ANYA]
    await _give(db, league_id, ME, ME, "foil", day)  # себе — без сообщения
    await hockey_notices.deliver_outfit_notices(factory, now=NOW, send=send)
    assert len(sent) == 2


@pytest.mark.asyncio
async def test_only_listed_leagues_have_the_right(db_session, monkeypatch) -> None:
    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    monkeypatch.setenv("KK_CAPTAIN_LEAGUES", f"{league_id + 1000}, 5")
    assert (await _evening(db, league_id, day=day))["captain_on"] is False
    with pytest.raises(RightClosed):
        from src.application.hockey_league_captain import chat_give

        await chat_give(
            db, league_id=league_id, captain_key=ME, day=day, to_pid=await _pid(db, SASHA), item="bag", now=NOW
        )
    monkeypatch.setenv("KK_CAPTAIN_LEAGUES", f"5,{league_id}")
    assert (await _evening(db, league_id, day=day))["captain_on"] is True


@pytest.mark.asyncio
async def test_one_tap_never_changes_an_existing_award(db_session) -> None:
    """Кнопка из сводки выдаёт, но не меняет — даже свою выдачу: менять только в «Вечере»."""
    from src.application.hockey_league_captain import chat_give, day_award

    db = db_session
    league_id = await _league(db, scope="extraliga")
    day = await _played_day(db, league_id, D1, BASIC)
    await _give(db, league_id, ME, ANYA, "bucket", day)
    with pytest.raises(AlreadyGiven):
        await chat_give(
            db, league_id=league_id, captain_key=ME, day=day, to_pid=await _pid(db, SASHA), item="wanted", now=NOW
        )
    assert (await day_award(db, league_id, day)).item == "bucket"
