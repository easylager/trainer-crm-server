"""TASK-446: тесты бота «Я здесь» — тексты, кандидаты, колбэк кнопок (без Telegram)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.bot import checkin_bot as cb
from src.application import ice_checkins as ic
from src.shared.config import Settings, get_settings


def _tg() -> int:
    return 7_000_000_000 + (uuid.uuid4().int % 2_000_000_000)


# ── Тексты ───────────────────────────────────────────────────────────────


def test_prompt_text_plain():
    t = cb.prompt_text("Чижовка-Арена", "21:15", None)
    assert t.startswith("Ты на катке?\nЧижовка-Арена, сеанс идёт до 21:15.")
    assert t.endswith("серию.")
    assert "недел" not in t.split("серию")[-1]


def test_prompt_text_streak():
    t = cb.prompt_text("Арена", "20:00", 4)
    assert "это будет 4-я неделя подряд" in t


def test_prompt_keyboard():
    kb = cb.prompt_keyboard(42)
    row1 = [b.callback_data for b in kb.inline_keyboard[0]]
    assert row1 == ["ci:42:1", "ci:42:2", "ci:42:3"]
    assert kb.inline_keyboard[1][0].callback_data == "ci:42:no"


def test_answered_text():
    assert cb.answered_text(6, 0) == "Отмечено · 6-й раз за сезон."
    assert "Серия: 3" in cb.answered_text(6, 3)


# ── Кандидаты и отправка ─────────────────────────────────────────────────


async def _seed_ongoing(*, name: str) -> tuple[int, int, int]:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            city_id = int((await conn.execute(
                text("INSERT INTO cities (name, country, price_group, is_active, sort_order) "
                     "VALUES (:n,'BY','BY_BASE',true,-1) RETURNING id"), {"n": name})).scalar_one())
            arena_id = int((await conn.execute(
                text("INSERT INTO arenas (city_id,name,address,venue_type,is_active,is_confirmed) "
                     "VALUES (:c,:n,'a','ice',true,true) RETURNING id"),
                {"c": city_id, "n": f"Каток {name}"})).scalar_one())
            now = datetime.now(timezone.utc)
            s, e = now - timedelta(minutes=30), now + timedelta(minutes=90)
            sid = int((await conn.execute(
                text("INSERT INTO ice_sessions (arena_id,kind,starts_at_utc,ends_at_utc,local_date,"
                     " starts_at_local,ends_at_local,currency_code,status,source_id,observed_at)"
                     " VALUES (:a,'public_skate',:s,:e,:d,:sl,:el,'BYN','active','admin',:o) RETURNING id"),
                {"a": arena_id, "s": s, "e": e, "d": (s + timedelta(hours=3)).date(),
                 "sl": (s + timedelta(hours=3)).time(), "el": (e + timedelta(hours=3)).time(),
                 "o": now})).scalar_one())
    finally:
        await engine.dispose()
    return city_id, arena_id, sid


async def _cleanup_bot(*, city_id: int, arena_id: int, tgs: list[int]) -> None:
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            for t in tgs:
                for tbl in ("ice_checkin_prompts", "ice_checkin_intents", "ice_checkins",
                            "ice_checkin_mutes", "clients"):
                    col = "telegram_id" if tbl != "ice_checkin_mutes" else "telegram_id"
                    await conn.execute(text(f"DELETE FROM {tbl} WHERE {col} = :t"), {"t": t})
            await conn.execute(text("DELETE FROM ice_sessions WHERE arena_id = :a"), {"a": arena_id})
            await conn.execute(text("DELETE FROM arenas WHERE id = :a"), {"a": arena_id})
            await conn.execute(text("DELETE FROM cities WHERE id = :c"), {"c": city_id})
    finally:
        await engine.dispose()


async def _session():
    engine = create_async_engine(Settings().database_url)
    conn = await engine.connect()
    return engine, conn


@pytest.mark.asyncio
async def test_candidates_and_eligibility(monkeypatch) -> None:
    """intent → кандидат; флаг выкл / отметка сегодня / mute → отсеиваются."""
    tg_on, tg_off, tg_done = _tg(), _tg(), _tg()
    city_id, arena_id, sid = await _seed_ongoing(name=f"cb-{uuid.uuid4().hex[:8]}")
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            for t in (tg_on, tg_off, tg_done):
                await conn.execute(
                    text("INSERT INTO ice_checkin_intents (telegram_id, session_id, kind) VALUES (:t,:s,'view')"),
                    {"t": t, "s": sid})
            await conn.execute(
                text("INSERT INTO clients (telegram_id, first_name, created_at) VALUES (:t,'M',:c)"),
                {"t": tg_done, "c": datetime.now(timezone.utc) - timedelta(days=30)})
            await conn.execute(
                text("INSERT INTO ice_checkins (telegram_id, session_id, arena_id, local_date, source)"
                     " VALUES (:t,:s,:a,:d,'app')"),
                {"t": tg_done, "s": sid, "a": arena_id,
                 "d": datetime.now(timezone.utc).astimezone(ic.MINSK).date()})
        monkeypatch.setenv("CLIENT_REDESIGN_S5_TELEGRAM_IDS", f"{tg_on},{tg_done}")
        monkeypatch.setenv("CLIENT_REDESIGN_S5_PERCENT", "0")
        get_settings.cache_clear()
        async with engine.begin() as conn:
            from sqlalchemy.ext.asyncio import AsyncSession
            session = AsyncSession(bind=conn)
            now = datetime.now(timezone.utc)
            cands = await ic.candidate_rows(session, now)
            ours = {int(r["telegram_id"]) for r in cands if int(r["session_id"]) == sid}
            assert {tg_on, tg_off, tg_done} <= ours
            eligible = await cb._eligible_telegram_ids(session, cands, now, get_settings())
            elig = {int(r["telegram_id"]) for r in eligible if int(r["session_id"]) == sid}
            assert tg_on in elig
            assert tg_off not in elig      # флаг выкл
            assert tg_done not in elig     # уже отмечался сегодня
            created = await cb.create_prompts(session, now, get_settings())
            rows = [r for r in created if int(r["session_id"]) == sid]
            assert [int(r["telegram_id"]) for r in rows] == [tg_on]
            # повтор — ON CONFLICT не дублирует
            created2 = await cb.create_prompts(session, now, get_settings())
            assert not [r for r in created2 if int(r["session_id"]) == sid]
    finally:
        await engine.dispose()
        get_settings.cache_clear()
        await _cleanup_bot(city_id=city_id, arena_id=arena_id, tgs=[tg_on, tg_off, tg_done])


@pytest.mark.asyncio
async def test_due_prompts_one_per_day_and_send() -> None:
    """due_prompts: максимум один вопрос на человека в сутки; остальные → skipped."""
    tg = _tg()
    city_id, arena_id, sid = await _seed_ongoing(name=f"cb-{uuid.uuid4().hex[:8]}")
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO ice_checkin_prompts (telegram_id, session_id, arena_id, reason, due_at, status)"
                     " VALUES (:t,:s,:a,'intent',:d,'pending')"),
                {"t": tg, "s": sid, "a": arena_id,
                 "d": datetime.now(timezone.utc) - timedelta(minutes=1)})
            # второй pending для другого сеанса того же tg
            sid2 = int((await conn.execute(
                text("INSERT INTO ice_sessions (arena_id,kind,starts_at_utc,ends_at_utc,local_date,"
                     " starts_at_local,ends_at_local,currency_code,status,source_id,observed_at)"
                     " SELECT :a,'public_skate',starts_at_utc,ends_at_utc,local_date,starts_at_local,"
                     " ends_at_local,'BYN','active','admin',NOW() FROM ice_sessions WHERE id=:s RETURNING id"),
                {"a": arena_id, "s": sid})).scalar_one())
            await conn.execute(
                text("INSERT INTO ice_checkin_prompts (telegram_id, session_id, arena_id, reason, due_at, status)"
                     " VALUES (:t,:s,:a,'intent',:d,'pending')"),
                {"t": tg, "s": sid2, "a": arena_id, "d": datetime.now(timezone.utc) - timedelta(minutes=1)})
        async with engine.begin() as conn:
            from sqlalchemy.ext.asyncio import AsyncSession
            session = AsyncSession(bind=conn)
            send = await cb.due_prompts(session, datetime.now(timezone.utc))
            ours = [r for r in send if int(r["telegram_id"]) == tg]
            assert len(ours) == 1
            # отправка фейковым ботом
            bot = MagicMock()
            bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=10))
            sent = await cb.send_due_prompts(bot, session, datetime.now(timezone.utc))
            assert sent >= 1
            st = (await session.execute(
                text("SELECT status, sent_at, message_id FROM ice_checkin_prompts WHERE telegram_id=:t ORDER BY id"),
                {"t": tg})).mappings().all()
            statuses = sorted(str(r["status"]) for r in st)
            assert "sent" in statuses and "skipped" in statuses
    finally:
        await engine.dispose()
        await _cleanup_bot(city_id=city_id, arena_id=arena_id, tgs=[tg])


@pytest.mark.asyncio
async def test_callback_answer_and_mute_twice() -> None:
    """Ответ «В меру» → отметка source=chat; «нет» дважды → muted_until +30d."""
    tg = _tg()
    city_id, arena_id, sid = await _seed_ongoing(name=f"cb-{uuid.uuid4().hex[:8]}")
    engine = create_async_engine(Settings().database_url)
    try:
        async with engine.begin() as conn:
            pid = int((await conn.execute(
                text("INSERT INTO ice_checkin_prompts (telegram_id, session_id, arena_id, reason, due_at, status)"
                     " VALUES (:t,:s,:a,'intent',:d,'sent') RETURNING id"),
                {"t": tg, "s": sid, "a": arena_id, "d": datetime.now(timezone.utc) - timedelta(minutes=1)}
            )).scalar_one())
        # фейковый query
        def make_query(data):
            q = MagicMock()
            q.data = data
            q.from_user = SimpleNamespace(id=tg)
            q.answer = AsyncMock()
            q.message = SimpleNamespace(edit_text=AsyncMock(), edit_reply_markup=AsyncMock())
            return q

        # checkin_bot сам открывает async_session_factory → реальная БД, ок.
        q = make_query(f"ci:{pid}:2")
        await cb.on_checkin_button(q)
        q.answer.assert_called()
        async with engine.begin() as conn:
            row = (await conn.execute(
                text("SELECT load_level, source FROM ice_checkins WHERE telegram_id=:t"), {"t": tg})).mappings().first()
            assert row is not None and row["source"] == "chat" and row["load_level"] == 2
            st = (await conn.execute(
                text("SELECT status FROM ice_checkin_prompts WHERE id=:i"), {"i": pid})).scalar()
            assert st == "answered"
        # «нет» дважды → стрик 2 → muted_until ≈ +30d (каждый промпт — свой сеанс, uq по (tg,session))
        for i in range(2):
            async with engine.begin() as conn:
                sx = int((await conn.execute(
                    text("INSERT INTO ice_sessions (arena_id,kind,starts_at_utc,ends_at_utc,local_date,"
                         " starts_at_local,ends_at_local,currency_code,status,source_id,observed_at)"
                         " SELECT :a,'public_skate',starts_at_utc,ends_at_utc,local_date,starts_at_local,"
                         " ends_at_local,'BYN','active','admin',NOW() FROM ice_sessions WHERE id=:s RETURNING id"),
                    {"a": arena_id, "s": sid})).scalar_one())
                pid2 = int((await conn.execute(
                    text("INSERT INTO ice_checkin_prompts (telegram_id, session_id, arena_id, reason, due_at, status)"
                         " VALUES (:t,:s,:a,'intent',:d,'sent') RETURNING id"),
                    {"t": tg, "s": sx, "a": arena_id, "d": datetime.now(timezone.utc)})).scalar_one())
            q2 = make_query(f"ci:{pid2}:no")
            await cb.on_checkin_button(q2)
            q2.answer.assert_called_with("Понял, сегодня не спрашиваю")
        async with engine.connect() as conn:
            mute = (await conn.execute(
                text("SELECT not_here_streak, muted_until FROM ice_checkin_mutes WHERE telegram_id=:t AND arena_id=:a"),
                {"t": tg, "a": arena_id})).mappings().first()
            assert mute["not_here_streak"] >= 2 and mute["muted_until"] is not None
    finally:
        await engine.dispose()
        await _cleanup_bot(city_id=city_id, arena_id=arena_id, tgs=[tg])
