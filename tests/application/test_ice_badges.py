"""TASK-451: значки волны 1 — правила (чистые функции) и вручение в БД."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.application import ice_badges as ib
from src.application import ice_checkins as ic
from src.shared.config import Settings

TODAY = date(2026, 11, 24)  # вторник, неделя 23–29.11


def _weekly(n: int, today: date = TODAY) -> list[date]:
    """По одной отметке в n последних завершённых неделях."""
    monday = today - timedelta(days=today.weekday())
    return [monday - timedelta(days=7 * i - 4) for i in range(1, n + 1)]


class TestProgressMap:
    def test_empty(self):
        prog = ib.progress_map([], TODAY)
        assert all(v == 0 for v in prog.values())

    def test_first_checkin(self):
        prog = ib.progress_map([TODAY], TODAY)
        assert prog["first_ice"] == 1 and prog["days_10"] == 1 and prog["days_25"] == 1
        assert prog["streak_3"] == 1  # одна неделя из трёх

    def test_streak_thresholds(self):
        prog = ib.progress_map(_weekly(3) + [TODAY], TODAY)
        assert prog["streak_3"] == 3 and prog["streak_5"] == 4 and prog["streak_10"] == 4

    def test_streak_caps_at_total(self):
        prog = ib.progress_map(_weekly(12) + [TODAY], TODAY)
        assert prog["streak_10"] == 10

    def test_days_thresholds(self):
        dates = [TODAY - timedelta(days=i) for i in range(10)]
        prog = ib.progress_map(dates, TODAY)
        assert prog["days_10"] == 10 and prog["days_25"] == 10


class TestEarnedKeys:
    def test_none(self):
        assert ib.earned_keys(ib.progress_map([], TODAY)) == set()

    def test_first_ice(self):
        assert ib.earned_keys(ib.progress_map([TODAY], TODAY)) == {"first_ice"}

    def test_streak_3(self):
        got = ib.earned_keys(ib.progress_map(_weekly(3) + [TODAY], TODAY))
        assert got == {"first_ice", "streak_3"}

    def test_all(self):
        dates = _weekly(10) + [TODAY - timedelta(days=i) for i in range(25)]
        got = ib.earned_keys(ib.progress_map(dates, TODAY))
        assert got == {"first_ice", "streak_3", "streak_5", "streak_10", "days_10", "days_25"}


class TestNextInFamily:
    def test_streak_next(self):
        # серия 4 → после «Не растаял» (3) ближайший «Крепкий лёд» (5), осталась 1 неделя
        prog = ib.progress_map(_weekly(3) + [TODAY], TODAY)
        nxt = ib.next_in_family("streak_3", prog)
        assert nxt["key"] == "streak_5" and nxt["remaining"] == 1

    def test_last_in_family_falls_to_closest(self):
        prog = ib.progress_map(_weekly(10) + [TODAY], TODAY)
        assert ib.next_in_family("streak_10", prog) is None

    def test_intro_has_no_family_next(self):
        prog = ib.progress_map([TODAY], TODAY)
        assert ib.next_in_family("first_ice", prog) is None


class TestClosestUnearned:
    def test_picks_highest_ratio(self):
        # 2 дня сезона (2/10 = 0.2) против серии 1 неделя (1/3 ≈ 0.33) → серия ближе
        prog = ib.progress_map([TODAY - timedelta(days=1), TODAY], TODAY)
        best = ib.closest_unearned(prog, {"first_ice"})
        assert best["key"] == "streak_3" and best["remaining"] == 2

    def test_skips_earned(self):
        prog = ib.progress_map(_weekly(3) + [TODAY], TODAY)
        best = ib.closest_unearned(prog, {"first_ice", "streak_3"})
        assert best["key"] == "streak_5"  # 3/5 = 0.6 — ближе всех


class TestRemainingWord:
    def test_forms(self):
        assert ib.remaining_word("streak", 1) == "1 неделя"
        assert ib.remaining_word("streak", 2) == "2 недели"
        assert ib.remaining_word("season", 5) == "5 дней"


class TestNearestLine:
    def test_streak_line(self):
        prog = ib.progress_map(_weekly(3) + [TODAY], TODAY)
        line = ib.nearest_line(prog, {"first_ice", "streak_3"})
        assert line == "До «Крепкого льда» — 1 неделя"

    def test_none_when_all_earned(self):
        dates = _weekly(10) + [TODAY - timedelta(days=i) for i in range(25)]
        prog = ib.progress_map(dates, TODAY)
        assert ib.nearest_line(prog, set(ib.BADGE_KEYS)) is None


# ── Вручение в БД (коммитом — evaluate_and_award пишет ice_badges) ────────


def _tg() -> int:
    return 7_000_000_000 + (uuid.uuid4().int % 2_000_000_000)


async def _seed_arena(conn, name: str) -> int:
    city_id = int((await conn.execute(
        text("INSERT INTO cities (name, country, price_group, is_active, sort_order) "
             "VALUES (:n,'BY','BY_BASE',true,-1) RETURNING id"), {"n": name})).scalar_one())
    return int((await conn.execute(
        text("INSERT INTO arenas (city_id,name,address,venue_type,is_active,is_confirmed) "
             "VALUES (:c,:n,'a','ice',true,true) RETURNING id"),
        {"c": city_id, "n": f"Каток {name}"})).scalar_one())


async def _insert_checkins(conn, tg: int, arena_id: int, dates: list[date]) -> None:
    """Отметки в заданные даты: по одному сеансу на дату (uq tg+session)."""
    for d in dates:
        sid = int((await conn.execute(
            text(
                "INSERT INTO ice_sessions (arena_id,kind,starts_at_utc,ends_at_utc,local_date,"
                " starts_at_local,ends_at_local,currency_code,status,source_id,observed_at)"
                " VALUES (:a,'public_skate',:s,:e,:d,TIME '18:00',TIME '20:00','BYN','active','admin',NOW())"
                " RETURNING id"),
            {"a": arena_id, "s": datetime(d.year, d.month, d.day, 15, 0, tzinfo=timezone.utc),
             "e": datetime(d.year, d.month, d.day, 17, 0, tzinfo=timezone.utc), "d": d})).scalar_one())
        await conn.execute(
            text(
                "INSERT INTO ice_checkins (telegram_id, session_id, arena_id, local_date, source)"
                " VALUES (:t, :s, :a, :d, 'app')"
            ),
            {"t": tg, "s": sid, "a": arena_id, "d": d},
        )


async def _cleanup(conn, tg: int) -> None:
    await conn.execute(text("DELETE FROM ice_badges WHERE telegram_id = :t"), {"t": tg})
    await conn.execute(text("DELETE FROM ice_checkins WHERE telegram_id = :t"), {"t": tg})


@pytest.mark.asyncio
async def test_award_idempotent_and_seen() -> None:
    """evaluate_and_award: пороги, повтор без дублей, pending/seen."""
    tg = _tg()
    engine = create_async_engine(Settings().database_url)
    arena_id = None
    try:
        async with engine.begin() as conn:
            await _cleanup(conn, tg)
            arena_id = await _seed_arena(conn, f"ib-{uuid.uuid4().hex[:8]}")
            await _insert_checkins(conn, tg, arena_id, _weekly(3) + [TODAY])
        async with engine.begin() as conn:
            session = AsyncSession(bind=conn)
            awarded = await ib.evaluate_and_award(session, tg, None, TODAY)
            keys = {b["key"] for b in awarded}
            assert keys == {"first_ice", "streak_3"}
            first = next(b for b in awarded if b["key"] == "streak_3")
            assert first["next"] is not None and first["next"]["key"] == "streak_5"
            assert first["earned"] is True and first["progress"]["done"] == 3
            # повтор — ничего нового, дублей нет
            assert await ib.evaluate_and_award(session, tg, None, TODAY) == []
            # pending → оба значка до показа
            pending = await ib.pending_badges(session, tg, None, TODAY)
            assert {b["key"] for b in pending} == {"first_ice", "streak_3"}
            # seen
            assert await ib.mark_shown(session, tg, None, ["first_ice", "streak_3", "bogus"]) == 2
            assert await ib.pending_badges(session, tg, None, TODAY) == []
            # повторный seen — уже не трогает (shown_at стоит)
            assert await ib.mark_shown(session, tg, None, ["first_ice"]) == 0
        async with engine.connect() as conn:
            n = (await conn.execute(
                text("SELECT COUNT(*) FROM ice_badges WHERE telegram_id = :t"), {"t": tg})).scalar()
            assert n == 2
    finally:
        async with engine.begin() as conn:
            await _cleanup(conn, tg)
            if arena_id is not None:
                await conn.execute(
                    text("DELETE FROM ice_sessions WHERE arena_id = :a"), {"a": arena_id})
                cid = (await conn.execute(
                    text("SELECT city_id FROM arenas WHERE id = :a"), {"a": arena_id})).scalar()
                await conn.execute(text("DELETE FROM arenas WHERE id = :a"), {"a": arena_id})
                if cid is not None:
                    await conn.execute(text("DELETE FROM cities WHERE id = :c"), {"c": cid})
        await engine.dispose()


@pytest.mark.asyncio
async def test_badges_payload_progress() -> None:
    """badges_payload: все 6 значков, earned/progress корректны."""
    tg = _tg()
    engine = create_async_engine(Settings().database_url)
    arena_id = None
    try:
        async with engine.begin() as conn:
            arena_id = await _seed_arena(conn, f"ib-{uuid.uuid4().hex[:8]}")
            await _insert_checkins(conn, tg, arena_id, _weekly(3) + [TODAY])
            session = AsyncSession(bind=conn)
            await ib.evaluate_and_award(session, tg, None, TODAY)
        async with engine.begin() as conn:
            session = AsyncSession(bind=conn)
            out = await ib.badges_payload(session, tg, None, TODAY)
            assert len(out) == 6
            by = {b["key"]: b for b in out}
            assert by["first_ice"]["earned"] is True
            assert by["streak_3"]["earned"] is True
            # серия 3 прошлых + текущая = 4 недели → «Крепкий лёд» (5) не хватает одной
            assert by["streak_5"]["earned"] is False
            assert by["streak_5"]["progress"] == {"done": 4, "total": 5}
            assert by["streak_10"]["progress"]["done"] == 4
            assert by["days_10"]["progress"] == {"done": 4, "total": 10}
            assert by["days_25"]["earned"] is False
    finally:
        async with engine.begin() as conn:
            await _cleanup(conn, tg)
            if arena_id is not None:
                await conn.execute(
                    text("DELETE FROM ice_sessions WHERE arena_id = :a"), {"a": arena_id})
                cid = (await conn.execute(
                    text("SELECT city_id FROM arenas WHERE id = :a"), {"a": arena_id})).scalar()
                await conn.execute(text("DELETE FROM arenas WHERE id = :a"), {"a": arena_id})
                if cid is not None:
                    await conn.execute(text("DELETE FROM cities WHERE id = :c"), {"c": cid})
        await engine.dispose()
