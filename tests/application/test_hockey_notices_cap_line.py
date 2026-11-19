"""TASK-431: строка про кепку дня в вечерней сводке — одна на лигу, где кепку решил матч этой сводки."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy import text

from src.application import hockey_notices
from src.application.hockey_game import make_pick, score_finished_matches
from src.application.hockey_matches import set_manual_result
from src.application.hockey_notices import cap_line, deliver, due_notices
from src.ingestion.hockey_sources import MINSK_TZ


@pytest.fixture(autouse=True)
def _captain_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Право капитана включено во всех лигах (KK_CAPTAIN_LEAGUES=*); тесты выключения ставят своё."""
    monkeypatch.setenv("KK_CAPTAIN_LEAGUES", "*")


OLEG, ANYA, MAX, DIMA = 9431001, 9431002, 9431003, 9431004
NAMES = {OLEG: "Олег", ANYA: "Аня", MAX: "Макс", DIMA: "Дима"}


def at(hour: int, minute: int = 0, *, day: int = 10) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=MINSK_TZ)


@pytest.fixture(autouse=True)
def bot_env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)
    hockey_notices._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    @asynccontextmanager
    async def make():
        yield db_session

    return make


class Outbox:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, list]] = []

    async def __call__(self, chat_id: int, body: str, buttons) -> str:
        self.sent.append((chat_id, body, buttons))
        return hockey_notices.SENT


async def _match(db, mid: str, starts_at: datetime, home: str, away: str) -> int:
    return (
        await db.execute(
            text("""INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                    VALUES ('hockeyby', 'extraliga', :mid, :home, :away, :t) RETURNING id"""),
            {"mid": mid, "home": home, "away": away, "t": starts_at},
        )
    ).scalar_one()


async def _finish(db, match_id: int, home: int, away: int, when: datetime) -> None:
    await set_manual_result(db, match_id, home_score=home, away_score=away, decided_in="regulation", now=when)
    await score_finished_matches(db, now=when)


async def _league(db, name: str, members) -> int:
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES (:n, :c, :o, 'extraliga', 'season', :s, :e) RETURNING id"""),
            {"n": name, "c": f"K431{len(name):04d}", "o": members[0], "s": at(0, day=1), "e": at(0, day=30)},
        )
    ).scalar_one()
    for key in members:
        await db.execute(
            text("INSERT INTO hockey_league_members (league_id, player_key, joined_at) VALUES (:l, :k, :j)"),
            {"l": league_id, "k": key, "j": at(0, day=2)},
        )
    return int(league_id)


def test_cap_line_text() -> None:
    assert cap_line(league_name="Бригада", holders=("Олег",), mine=False) == (
        "<b>Кепка дня</b> в лиге «Бригада» — Олег: хуже всех угадывал в этот день."
    )
    assert cap_line(league_name="Бригада", holders=("ты",), mine=True) == (
        "<b>Кепка дня</b> в лиге «Бригада» — у тебя: хуже всех угадывал в этот день."
    )
    assert cap_line(league_name="<b>", holders=("ты", "Олег"), mine=True) == (
        "<b>Кепка дня</b> в лиге «&lt;b&gt;» — ты и Олег: хуже всех угадывали в этот день."
    )


@pytest.mark.asyncio
async def test_summary_gets_the_cap_line_only_when_its_match_closes_the_day(db_session, factory) -> None:
    db = db_session
    first = await _match(db, "k431-1", at(16), "Юность-Минск", "Неман")
    last = await _match(db, "k431-2", at(19), "Гомель", "Шахтёр")
    for key in NAMES:
        await db.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, :n)"), {"k": key, "n": NAMES[key]}
        )
    league_id = await _league(db, "Бригада", [OLEG, ANYA, MAX, DIMA])
    # 1-й матч 3:1: Аня в точку, Макс за хозяев, Олег мимо. 2-й матч 2:3: Аня и Макс угадали, Олег мимо.
    picks = {
        first: {ANYA: {"home_score": 3, "away_score": 1}, MAX: {"side": "home"}, OLEG: {"side": "away"}},
        last: {ANYA: {"side": "away"}, MAX: {"side": "away"}, OLEG: {"side": "home"}},
    }
    for match_id, by in picks.items():
        for key, kw in by.items():
            await make_pick(db, player_key=key, display_name=NAMES[key], match_id=match_id, now=at(10), **kw)
    await _finish(db, first, 3, 1, at(18, 30))

    early = await due_notices(db, now=at(18, 40))
    assert early and all("Кепка дня" not in n.text for n in early)  # день лиги не сыгран
    await deliver(factory, now=at(18, 40), send=Outbox())

    await _finish(db, last, 2, 3, at(21, 30))
    notices = {n.player_key: n for n in await due_notices(db, now=at(21, 40))}
    assert set(notices) == {ANYA, MAX, OLEG}  # Дима не ходил — итога нет, строки тоже
    # Аня — капитан вечера (TASK-432): после строки про кепку — её право, отдельной строкой.
    assert notices[ANYA].text.endswith(
        "<b>Кепка дня</b> в лиге «Бригада» — Олег: хуже всех угадывал в этот день.\n"
        "<b>Ты капитан</b> в лиге «Бригада». Олег — 0 из 2: выдать плакат? Или выбери сам в «Вечере»."
    )
    # Выдача в один тап: кнопка «Выдать плакат» над «Вечером в лиге» — Олегу, вечер 10 ноября.
    give = [b for row in notices[ANYA].buttons for b in row if b.get("callback_data", "").startswith("kk:o:")]
    assert [b["text"] for b in give] == ["Выдать плакат"]
    assert give[0]["callback_data"].startswith(f"kk:o:{league_id}:261110:") and give[0]["callback_data"].endswith(
        ":wanted"
    )
    assert not any("kk:o:" in b.get("callback_data", "") for row in notices[MAX].buttons for b in row)
    assert "Ты капитан" not in notices[MAX].text and "Ты капитан" not in notices[OLEG].text
    assert notices[OLEG].text.endswith("<b>Кепка дня</b> в лиге «Бригада» — у тебя: хуже всех угадывал в этот день.")
    urls = [b.get("url", "") for row in notices[MAX].buttons for b in row]
    labels = [b["text"] for row in notices[MAX].buttons for b in row]
    assert "Вечер в лиге" in labels
    assert any(f"kkv_{league_id}_20261110" in u for u in urls)
    assert labels[-1] == "Отключить такие сообщения"  # кнопка вечера — выше «Отключить»
    assert hockey_notices.KIND_RESULT == notices[MAX].kind  # новых видов нет: это тот же итог


@pytest.mark.asyncio
async def test_no_cap_line_when_cap_is_not_played(db_session) -> None:
    db = db_session
    m = await _match(db, "k431-3", at(19), "Гомель", "Шахтёр")
    for key in (OLEG, ANYA):
        await db.execute(
            text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, :n)"), {"k": key, "n": NAMES[key]}
        )
    await _league(db, "Двое", [OLEG, ANYA])
    await make_pick(db, player_key=OLEG, display_name="Олег", match_id=m, side="home", now=at(10))
    await make_pick(db, player_key=ANYA, display_name="Аня", match_id=m, side="away", now=at(10))
    await _finish(db, m, 2, 3, at(21, 30))
    notices = await due_notices(db, now=at(21, 40))
    assert notices and all("Кепка дня" not in n.text for n in notices)  # в споре двое — кепку не разыгрывали
    assert all("Вечер в лиге" not in [b["text"] for row in n.buttons for b in row] for n in notices)
