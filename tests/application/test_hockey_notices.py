"""TASK-335: напоминание за час и итог в бот — кому, что и ровно один раз."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from src.application.hockey_game import make_pick, score_finished_matches, set_double
from src.application.hockey_leagues import create_league, join_by_code
from src.application.hockey_matches import set_manual_result
from src.application.hockey_notices import deliver, due_notices, set_remind
from src.application.hockey_races import close_due_races, ensure_month_race, mark_calendar_synced
from src.ingestion.hockey_sources import MINSK_TZ

SASHA, KATYA = 9360001, 9360002
NOV = datetime(2026, 11, 10, 12, 0, tzinfo=MINSK_TZ)


@pytest.fixture(autouse=True)
def bot_env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    monkeypatch.setenv("CLIENT_BOT_MAIN_MINI_APP", "1")
    monkeypatch.delenv("CLIENT_MINI_APP_SHORT_NAME", raising=False)


async def _match(db_session, mid: str, starts_at: datetime) -> int:
    return (
        await db_session.execute(
            text("""
                INSERT INTO hockey_matches (source, source_match_id, home_team, away_team, starts_at)
                VALUES ('hcdinamo', :mid, 'Динамо-Минск', 'Трактор', :starts_at) RETURNING id
                """),
            {"mid": mid, "starts_at": starts_at},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_reminder_an_hour_before_only_when_on_and_only_once(db_session) -> None:
    starts = datetime(2026, 11, 20, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "n1", starts)
    await set_remind(db_session, SASHA, True, display_name="Саша")
    await set_remind(db_session, KATYA, False, display_name="Катя")
    hour_before = starts - timedelta(minutes=55)
    assert await due_notices(db_session, now=starts - timedelta(hours=2)) == []

    notices = await due_notices(db_session, now=hour_before)
    assert [(n.kind, n.player_key) for n in notices] == [("before", SASHA)]
    n = notices[0]
    assert "<b>Через час:</b> Динамо-Минск — Трактор, 19:00." in n.text
    assert "Хода ещё нет" in n.text
    assert [b["text"] for b in n.buttons[0]] == ["За Динамо-Минск", "За Трактор"]
    assert n.buttons[0][0]["url"] == f"https://t.me/glide_test_bot?startapp=kkn_{m}_h"
    assert n.buttons[1][0] == {"text": "Не напоминать", "url": "https://t.me/glide_test_bot?startapp=kkoff"}

    sent: list[tuple[int, str]] = []

    async def send(chat_id: int, body: str, buttons) -> bool:
        sent.append((chat_id, body))
        return True

    @asynccontextmanager
    async def factory():
        yield db_session

    assert await deliver(factory, now=hour_before, send=send) == {"sent": 1, "failed": 0}
    assert await deliver(factory, now=hour_before + timedelta(minutes=10), send=send) == {"sent": 0, "failed": 0}
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_reminder_with_move_and_double_names_the_month_final(db_session) -> None:
    race = await ensure_month_race(db_session, now=NOV)
    starts = datetime(2026, 11, 30, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "n2", starts)
    await make_pick(db_session, player_key=SASHA, display_name="Саша", match_id=m, home_score=4, away_score=1, now=NOV)
    await set_double(db_session, player_key=SASHA, match_id=m, on=True, now=NOV)
    await mark_calendar_synced(db_session, now=datetime(2026, 11, 25, tzinfo=MINSK_TZ))
    await set_remind(db_session, SASHA, True)
    n = (await due_notices(db_session, now=starts - timedelta(minutes=50)))[0]
    assert n.text == (
        "<b>Через час:</b> Динамо-Минск — Трактор, 19:00. Финал ноября.\nТвой ход — 4:1, ×2. Поменять можно до начала."
    )
    assert race.id


@pytest.mark.asyncio
async def test_result_of_the_month_final_tells_who_has_the_crown(db_session) -> None:
    league = await create_league(db_session, owner_key=SASHA, owner_name="Саша", name="ОХМ")
    await join_by_code(db_session, player_key=KATYA, display_name="Катя", code=league.invite_code)
    await db_session.execute(
        text("UPDATE hockey_league_members SET joined_at = :at WHERE league_id = :l"),
        {"at": datetime(2026, 11, 1, tzinfo=MINSK_TZ), "l": league.id},
    )
    await ensure_month_race(db_session, now=NOV)
    starts = datetime(2026, 11, 30, 19, 0, tzinfo=MINSK_TZ)
    m = await _match(db_session, "n3", starts)
    for player, score in ((SASHA, (4, 1)), (KATYA, (2, 1))):
        await make_pick(
            db_session,
            player_key=player,
            display_name="x",
            match_id=m,
            home_score=score[0],
            away_score=score[1],
            now=NOV,
        )
    await set_double(db_session, player_key=SASHA, match_id=m, on=True, now=NOV)
    await set_remind(db_session, SASHA, True)
    await set_remind(db_session, KATYA, True)
    await mark_calendar_synced(db_session, now=datetime(2026, 11, 25, tzinfo=MINSK_TZ))
    done = starts + timedelta(hours=2, minutes=30)
    await set_manual_result(db_session, m, home_score=4, away_score=1, decided_in="regulation", now=done)
    await score_finished_matches(db_session, now=done)
    assert await close_due_races(db_session, now=done)

    by_player = {n.player_key: n for n in await due_notices(db_session, now=done) if n.kind == "result"}
    assert by_player[SASHA].text == (
        "<b>Динамо-Минск — Трактор 4:1.</b> В точку: +100 с ×2.\nЭто был финал ноября: корона в «ОХМ» — твоя."
    )
    assert by_player[KATYA].text.endswith("корона в «ОХМ» досталась: x.")
    assert by_player[SASHA].buttons[0][0]["text"] == "Итоги месяца"
    # Через шесть часов итог устарел — не шлём.
    assert await due_notices(db_session, now=done + timedelta(hours=7)) == []
