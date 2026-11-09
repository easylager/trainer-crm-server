"""TASK-359 (AC-007): матч Экстралиги с ходами без итога дольше 4 часов — одно сообщение админам."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from src.application.hockey_matches import set_manual_result
from src.application.hockey_stuck import STUCK_AFTER, notify_stuck_results, stuck_buttons, stuck_text
from src.ingestion.hockey_sources import MINSK_TZ

START = datetime(2026, 11, 9, 18, 30, tzinfo=MINSK_TZ)
PROBE = '{"home": 3, "away": 2, "decided_in": "regulation", "first_seen_at": "2026-11-09T21:34:00+03:00"}'
SASHA, KATYA = 9359501, 9359502


async def _match(
    db, *, league: str = "extraliga", status: str = "scheduled", starts_at: datetime = START, probe=None
) -> int:
    return int(
        (
            await db.execute(
                text("""
                    INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at, status,
                                                result_probe)
                    VALUES (:source, :league, :mid, 'Химик', 'Славутич', :starts_at, :status, CAST(:probe AS jsonb))
                    RETURNING id
                    """),
                {
                    "source": "hockeyby" if league == "extraliga" else "hcdinamo",
                    "league": league,
                    "mid": uuid.uuid4().hex,
                    "starts_at": starts_at,
                    "status": status,
                    "probe": probe,
                },
            )
        ).scalar_one()
    )


async def _pick(db, match_id: int, who: int = SASHA) -> None:
    await db.execute(
        text("INSERT INTO hockey_players (player_key, display_name) VALUES (:k, 'Игрок') ON CONFLICT DO NOTHING"),
        {"k": who},
    )
    await db.execute(
        text("INSERT INTO hockey_picks (match_id, player_key, side) VALUES (:m, :k, 'home')"), {"m": match_id, "k": who}
    )


class Outbox:
    def __init__(self, *, result: bool | None = True) -> None:
        self.sent: list[tuple[str, list]] = []
        self.result = result

    async def __call__(self, body: str, buttons) -> bool | None:
        self.sent.append((body, buttons))
        return self.result


@pytest.mark.asyncio
async def test_alert_comes_once_after_four_hours_and_never_repeats(db_session, _test_db_core) -> None:
    match = await _match(db_session, probe=PROBE)
    await _pick(db_session, match)
    factory = _test_db_core["factory"]
    out = Outbox()

    assert await notify_stuck_results(factory, now=START + STUCK_AFTER - timedelta(minutes=1), send=out) == 0
    assert out.sent == []
    assert await notify_stuck_results(factory, now=START + STUCK_AFTER + timedelta(minutes=1), send=out) == 1
    body, buttons = out.sent[0]
    assert "Химик — Славутич, 09.11 18:30" in body and "Ходов игроков: 1" in body
    assert "3:2, основное время" in body  # админ видит, что опрос уже видел
    assert buttons == [[{"text": "Поправить", "callback_data": f"hk:fix:{match}"}]]
    # Следующие тики молчат, пока итога нет.
    for extra in (10, 60, 600):
        assert await notify_stuck_results(factory, now=START + STUCK_AFTER + timedelta(minutes=extra), send=out) == 0
    assert len(out.sent) == 1


@pytest.mark.asyncio
async def test_no_alert_where_other_alerts_or_nothing_to_alert_already_exist(db_session, _test_db_core) -> None:
    late = START + timedelta(hours=5)
    # Нет ходов — итог ставится сразу, считать нечего.
    await _match(db_session)
    # Ручная проверка — карточка с кнопками уходит из notify_new_reviews.
    await _pick(db_session, await _match(db_session, status="review"))
    # КХЛ: итог проверяется своим циклом, через 3 ч 15 мин уже review и алерт.
    await _pick(db_session, await _match(db_session, league="khl"))
    # Итог есть.
    done = await _match(db_session)
    await _pick(db_session, done)
    await set_manual_result(db_session, done, home_score=3, away_score=2, decided_in="regulation", now=late)
    # Автоматически подтвердить уже нельзя (больше трёх суток): тот случай разбирает «зависший» алерт КХЛ/ручная очередь.
    await _pick(db_session, await _match(db_session, starts_at=START - timedelta(days=4)))

    out = Outbox()
    assert await notify_stuck_results(_test_db_core["factory"], now=late, send=out) == 0
    assert out.sent == []


@pytest.mark.asyncio
async def test_unreachable_admin_bot_retries_next_tick_but_still_sends_one(db_session, _test_db_core) -> None:
    match = await _match(db_session)
    await _pick(db_session, match)
    await _pick(db_session, match, KATYA)
    factory = _test_db_core["factory"]
    late = START + timedelta(hours=5)

    down = Outbox(result=False)
    assert await notify_stuck_results(factory, now=late, send=down) == 0
    up = Outbox()
    assert await notify_stuck_results(factory, now=late + timedelta(minutes=10), send=up) == 1
    assert "Ходов игроков: 2" in up.sent[0][0]
    assert await notify_stuck_results(factory, now=late + timedelta(minutes=20), send=up) == 0
    # Бот не настроен (None) — это лог без доставки, как у карточек проверки: повторять нечего.
    other = await _match(db_session, starts_at=START + timedelta(hours=1))
    await _pick(db_session, other)
    silent = Outbox(result=None)
    assert await notify_stuck_results(factory, now=late + timedelta(hours=1), send=silent) == 1
    assert await notify_stuck_results(factory, now=late + timedelta(hours=2), send=silent) == 0


def test_text_without_probe_and_escaping() -> None:
    row = SimpleNamespace(home_team="A<b>", away_team="Б", starts_at=START, probe=None, picks=3)
    body = stuck_text(row, now=START + timedelta(hours=5, minutes=20))
    assert "итога нет уже 5 ч" in body and "A&lt;b&gt;" in body and "hockey.by итог не показал" in body
    assert stuck_buttons(7) == [[{"text": "Поправить", "callback_data": "hk:fix:7"}]]


@pytest.mark.asyncio
async def test_hockey_matches_loop_runs_the_stuck_check_every_pass(monkeypatch) -> None:
    """Цикл матчей зовёт проверку на каждом проходе, пока Экстралига включена."""
    from src.application import hockey_review, hockey_stuck
    from src.bot import notification_loops as loops
    from src.shared import config

    stuck = AsyncMock(return_value=0)
    monkeypatch.setattr(hockey_stuck, "notify_stuck_results", stuck)
    monkeypatch.setattr(hockey_review, "notify_new_reviews", AsyncMock(return_value=0))
    monkeypatch.setattr(loops, "_extraliga_pass", AsyncMock(return_value={}))
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(extraliga_enabled=True, hockey_matches_enabled=False, site_matches_enabled=False),
    )

    async def stop(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(loops.asyncio, "sleep", stop)
    await loops.run_hockey_matches_loop()
    stuck.assert_awaited_once()
    assert stuck.await_args.kwargs["send"] is hockey_review.send_card_to_admins
