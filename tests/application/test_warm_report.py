"""TASK-428 (слой D): цифры прогрева — разовые, достижимые, воронка предложения, отправлено, блок в отчёте."""

from __future__ import annotations

from datetime import timedelta

import pytest
from kk_notify_helpers import make_factory
from sqlalchemy import text
from warm_helpers import ANNA, BORIS, VERA, at, seed_arena, seed_client, seed_visit, seed_warm_notice, seed_warm_prefs

from src.application import kk_notify_report as report
from src.application import warm_report as wr
from src.application.catalog_consumer_events import telegram_actor_hash
from src.application.stats_use_cases import get_platform_stats

SECRET = "r" * 40
SINCE, UNTIL = at(0, day=9), at(0, day=16)  # неделя 9–15 ноября по Минску


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", SECRET)


async def _event(db, kind: str, arena: int, when) -> None:
    await db.execute(
        text("INSERT INTO catalog_consumer_events (kind, surface, arena_id, occurred_at) VALUES (:k, 'x', :a, :w)"),
        {"k": kind, "a": arena, "w": when},
    )


async def _seed(db) -> int:
    arena = await seed_arena(db)
    for tid in (ANNA, BORIS, VERA):
        await seed_client(db, tid)
    await seed_visit(db, telegram_actor_hash(ANNA), at(12, day=12), arena_id=arena)  # разовый, достижим
    await seed_visit(db, telegram_actor_hash(BORIS), at(12, day=12), arena_id=arena)
    await seed_visit(db, telegram_actor_hash(BORIS), at(12, day=1), arena_id=arena)  # был и раньше — не разовый
    await seed_visit(db, telegram_actor_hash(VERA), at(12, day=13), arena_id=arena)
    await seed_warm_prefs(db, VERA, opted_out_at=at(9, day=14))  # разовая, но «Не присылать»
    await seed_visit(db, "web-actor-hash", at(12, day=14), arena_id=arena)  # сайт: разовый, недостижим
    await seed_visit(db, "old-actor", at(12, day=2), arena_id=arena)  # вне недели
    for kind, n in (("watch_offer_shown", 3), ("watch_offer_click", 2), ("watch_offer_subscribed", 1)):
        for i in range(n):
            await _event(db, kind, arena, at(12, day=10 + i))
    await seed_warm_notice(db, ANNA, "warm_nudge", at(10, day=13), ref="once")
    await seed_warm_notice(db, BORIS, "warm_today", None, created_at=at(10, day=13), failed=True)
    await db.execute(
        text("""
            INSERT INTO kk_notify_decisions (tick_at, player_key, phase, kind, decision, reason)
            VALUES (:t, :k, 'known', 'warm_nudge', 'dry_run', 'dry_run'), (:t2, :k, 'known', 'warm_nudge', 'dry_run', 'dry_run')
            """),
        {"t": at(10, day=11), "t2": at(11, day=11), "k": VERA},
    )
    return arena


@pytest.mark.asyncio
async def test_collect_counts(db_session) -> None:
    await _seed(db_session)
    data = await wr.collect(db_session, since=SINCE, until=UNTIL)
    assert (data.one_time, data.reachable) == (3, 1)  # Анна, Вера, сайт; написать можно только Анне
    assert data.offer == {"shown": 3, "click": 2, "closed": 0, "subscribed": 1}
    assert data.sent == {"warm_nudge": 1} and data.failed == 1
    assert (data.blocked, data.opted_out) == (0, 1)
    assert data.dry_run == {"warm_nudge": 1}  # разные люди, не записи журнала


@pytest.mark.asyncio
async def test_no_secret_means_nobody_reachable(db_session, monkeypatch) -> None:
    await _seed(db_session)
    monkeypatch.setenv("CATALOG_ACTOR_HMAC_SECRET", "")
    monkeypatch.setattr("src.shared.config.get_settings", lambda: type("S", (), {"catalog_actor_hmac_secret": ""})())
    data = await wr.collect(db_session, since=SINCE, until=UNTIL)
    assert data.reachable == 0


@pytest.mark.asyncio
async def test_section_text(db_session) -> None:
    await _seed(db_session)
    body = wr.render_section(await wr.collect(db_session, since=SINCE, until=UNTIL))
    assert "Разовых за неделю: 3, из них можно написать: 1." in body
    assert "показано 3, нажали 2, подписались 1, закрыли 0" in body
    assert "Отправлено 1: напоминание 1." in body
    assert "Нажали «Не присылать»: 1." in body
    assert "!" not in body


@pytest.mark.asyncio
async def test_weekly_report_has_warm_block_and_survives_its_failure(db_session, monkeypatch) -> None:
    await _seed(db_session)
    factory = make_factory(db_session)
    sent: list[str] = []

    async def admin(body: str):
        sent.append(body)
        return True

    assert await report.send_weekly_report_if_due(factory, now=at(10, day=16), send=admin) == "sent"
    assert "<b>Разовые посетители</b>" in sent[0] and "«Кто кого»" in sent[0]

    async def boom(*a, **kw):
        raise RuntimeError("warm down")

    monkeypatch.setattr(wr, "collect", boom)
    assert await report.send_weekly_report_if_due(factory, now=at(10, day=23), send=admin) == "sent"
    assert "Разовые посетители" not in sent[1] and "«Кто кого»" in sent[1]


@pytest.mark.asyncio
async def test_admin_stats_has_warm_slice(db_session, monkeypatch) -> None:
    await _seed(db_session)
    monkeypatch.setattr(wr, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: UNTIL)}))
    data = await get_platform_stats(db_session)
    warm = data["warm_visitors"]
    assert warm["one_time"] == 3 and warm["reachable"] == 1 and warm["sent_total"] == 1

    async def boom(*a, **kw):
        raise RuntimeError("warm down")

    monkeypatch.setattr(wr, "collect", boom)
    assert (await get_platform_stats(db_session))["warm_visitors"] is None  # сбой среза не роняет «Статистику»


def test_window_is_seven_days() -> None:
    assert UNTIL - SINCE == timedelta(days=7)
