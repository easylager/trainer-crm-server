"""TASK-426: правки по независимому ревью срезов 0–1. Гонка на двух настоящих соединениях, опечатки в флагах,
письма лиг через допуск, изоляция сбоев, ``gone``, окна отчёта."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from kk_notify_helpers import (
    KATYA,
    LESHA,
    SASHA,
    Outbox,
    at,
    make_factory,
    seed_match,
    seed_notice,
    seed_pick,
    seed_player,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.application import hockey_notices as hn
from src.application import kk_notify, kk_notify_gate as gate
from src.application import kk_notify_report as report
from src.application.kk_notify import Proposal, dispatch, run_tick
from src.application.kk_notify_gate import GateConfig, KindPolicy, admit
from src.ingestion.hockey_sources import MINSK_TZ

KIND = "before"
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({KIND}))
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    hn._RETRIES.clear()
    monkeypatch.setitem(gate.KIND_POLICY, KIND, KindPolicy(budgeted=True, weekly=True, new=True, priority=5))


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


async def _proposal(db, key: int, starts=None) -> Proposal:
    mid = await seed_match(db, starts or at(19, day=12))
    return Proposal(hn.Notice(KIND, key, mid, "тест", []))


async def _go(factory, proposal, *, send, now=None, config=CFG):
    now = now or at(12)
    return await dispatch(factory, proposal, phase="active", tick_at=now, send=send, config=config, clock=lambda: now)


# ---------- 1/7. настоящие соединения ----------

REAL_KEY = 9429001


@pytest.fixture
async def real():
    """Два независимых соединения к тестовой БД с настоящим коммитом; за собой всё удаляем."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    class Real:
        factory = staticmethod(maker)
        match_ids: list[int] = []

    async def clean() -> None:
        async with maker() as s:
            await s.execute(text("DELETE FROM kk_notify_decisions WHERE player_key = :k"), {"k": REAL_KEY})
            await s.execute(text("DELETE FROM hockey_players WHERE player_key = :k"), {"k": REAL_KEY})
            await s.execute(text("DELETE FROM hockey_matches WHERE source_match_id LIKE 'kk426-real-%'"))
            await s.commit()

    await clean()
    async with maker() as s:
        await s.execute(
            text("INSERT INTO hockey_players (player_key, display_name, created_at) VALUES (:k, 'Р', :t)"),
            {"k": REAL_KEY, "t": at(10, day=1)},
        )
        for i in range(2):
            mid = (
                await s.execute(
                    text(
                        """INSERT INTO hockey_matches (source, league, source_match_id, home_team, away_team, starts_at)
                            VALUES ('hockeyby', 'extraliga', :m, 'Юность', 'Шахтер', :t) RETURNING id"""
                    ),
                    {"m": f"kk426-real-{i}", "t": at(19, day=12)},
                )
            ).scalar_one()
            Real.match_ids.append(mid)
        await s.commit()
    try:
        yield Real
    finally:
        Real.match_ids = []
        await clean()
        await engine.dispose()


@pytest.mark.asyncio
async def test_race_two_connections_cannot_both_pass_daily_cap(real, monkeypatch) -> None:
    """Допуск и «занято» под одним замком: два цикла по одному игроку и разным матчам дают одну отправку."""
    real_claim = hn.claim

    async def slow_claim(session, notice):
        await asyncio.sleep(0.25)  # окно между допуском и занятием строки — как у загруженного цикла
        return await real_claim(session, notice)

    monkeypatch.setattr(hn, "claim", slow_claim)
    out = Outbox()
    props = [Proposal(hn.Notice(KIND, REAL_KEY, mid, "т", [])) for mid in real.match_ids]
    # строка «занято» получает created_at от БД (настоящее «сейчас»), поэтому часы — сегодня в полдень по Минску
    today = datetime.now(MINSK_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    results = await asyncio.gather(*[_go(real.factory, p, send=out, now=today) for p in props])
    assert len(out.sent) == 1, [(r.decision, r.reason) for r in results]
    assert sorted(r.reason or "ok" for r in results) == ["daily_cap", "ok"]


@pytest.mark.asyncio
async def test_claim_is_committed_before_telegram_call(real) -> None:
    """Из другого соединения строка «занято» уже видна, когда вызывается Telegram (занято без commit не пройдёт)."""
    seen: list[int] = []

    async def spy(chat_id, body, buttons):
        async with real.factory() as other:
            rows = await other.execute(
                text("SELECT 1 FROM hockey_notices WHERE player_key = :k AND kind = :kind"),
                {"k": REAL_KEY, "kind": KIND},
            )
            seen.append(len(rows.all()))
        return "ok"

    await _go(real.factory, Proposal(hn.Notice(KIND, REAL_KEY, real.match_ids[0], "т", [])), send=spy)
    assert seen == [1]


# ---------- 8. занятые, но ещё не отправленные строки считаются ----------


@pytest.mark.asyncio
async def test_in_flight_claimed_row_counts_toward_budget(db_session) -> None:
    await seed_player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "nomove", None, created_at=at(10, 0))  # занято, ещё не отправлено
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_failed_or_old_unsent_rows_do_not_count(db_session) -> None:
    await seed_player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "nomove", None, failed=True, created_at=at(10, 0))
    await seed_notice(db_session, SASHA, "mfinal", None, created_at=at(10, 0, day=8))
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)).allowed


# ---------- 2. сухой прогон не открывается опечаткой ----------


@pytest.mark.parametrize("value", ["", " ", "dry", "of", "nope", "2", "tru", "1", "true", "yes", "on"])
def test_dry_run_stays_on_unless_explicitly_disabled(monkeypatch, value) -> None:
    monkeypatch.setenv("KK_NOTIFY_DRY_RUN", value)
    assert GateConfig.from_settings().dry_run is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", " Off "])
def test_dry_run_turns_off_only_by_explicit_word(monkeypatch, value) -> None:
    monkeypatch.setenv("KK_NOTIFY_DRY_RUN", value)
    assert GateConfig.from_settings().dry_run is False


# ---------- 3. письма лиг — через допуск ----------


async def _league_notice(db, key: int) -> int:
    league_id = (
        await db.execute(
            text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                    VALUES ('Л', :c, :o, 'dinamo', 'month', :s, :e) RETURNING id"""),
            {"c": f"c{key}", "o": key, "s": at(0, day=1), "e": at(0, day=30)},
        )
    ).scalar_one()
    await db.execute(
        text("INSERT INTO hockey_league_notices (league_id, player_key, kind) VALUES (:l, :k, 'extended')"),
        {"l": league_id, "k": key},
    )
    return league_id


@pytest.mark.asyncio
@pytest.mark.parametrize("prefs", [{"blocked_at": at(1, day=9)}, {"notify_league": False}], ids=["blocked", "type"])
async def test_league_notice_goes_through_gate(db_session, factory, prefs) -> None:
    await seed_player(db_session, SASHA, **prefs)
    await _league_notice(db_session, SASHA)
    out = Outbox()
    counts = await hn.deliver_league_notices(factory, now=at(12), send=out)
    assert out.sent == [] and counts["skipped"] == 1
    journal = (await db_session.execute(text("SELECT kind, decision FROM kk_notify_decisions"))).all()
    assert [tuple(r) for r in journal] == [("league", "skip")]


@pytest.mark.asyncio
async def test_league_notice_sent_when_allowed_and_ignores_budget(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "nomove", at(10, 0))
    await _league_notice(db_session, SASHA)
    out = Outbox()
    await hn.deliver_league_notices(factory, now=at(12), send=out)
    assert len(out.sent) == 1


def test_tripwire_covers_league_path() -> None:
    src = (ROOT / "src/application/hockey_notices.py").read_text(encoding="utf-8")
    body = src[src.index("async def deliver_league_notices(") : src.index("# Telegram режет рассылку")]
    assert body.index("await admit(") < body.index("await send(")
    assert "league" in gate.KIND_POLICY


# ---------- 4. новый повод обязан быть в лимитах ----------


def test_register_kind_demands_budget(monkeypatch) -> None:
    monkeypatch.setattr(gate, "KIND_POLICY", dict(gate.KIND_POLICY))
    with pytest.raises(ValueError):
        gate.register_kind("zz", KindPolicy(budgeted=False, weekly=True, new=True))
    with pytest.raises(ValueError):
        gate.register_kind("zz", KindPolicy(budgeted=True, weekly=False, new=True))
    with pytest.raises(ValueError):
        gate.register_kind("zz", KindPolicy(budgeted=True, weekly=True, new=False))
    gate.register_kind("ok", KindPolicy(budgeted=True, weekly=True, new=True))
    gate.register_kind("free", KindPolicy(budgeted=False, new=True), allow_unbudgeted=True)
    assert {"ok", "free"} <= set(gate.KIND_POLICY)


# ---------- 5. сбой расчёта не роняет цикл ----------


@pytest.mark.asyncio
async def test_tick_setup_failures_never_raise(db_session, factory, monkeypatch) -> None:
    async def producer(session, *, now):
        return []

    def bad_settings(*a, **k):
        raise RuntimeError("config")

    monkeypatch.setattr(GateConfig, "from_settings", classmethod(bad_settings))
    assert await run_tick(factory, now=at(12), send=Outbox(), producers={KIND: producer}) == {"error": 1}
    monkeypatch.undo()

    async def bad_facts(*a, **k):
        raise RuntimeError("db")

    monkeypatch.setattr(kk_notify, "load_player_facts", bad_facts)
    monkeypatch.setitem(gate.KIND_POLICY, KIND, KindPolicy(budgeted=True, weekly=True, new=True))
    # Писать некому — факты по игрокам не грузятся вовсе (пятничное приглашение крутится в каждом проходе).
    assert await run_tick(factory, now=at(12), send=Outbox(), producers={KIND: producer}, config=CFG) == {}
    await seed_player(db_session, KATYA, registered=at(10, day=1))
    proposal = await _proposal(db_session, KATYA)

    async def busy(session, *, now):
        return [proposal]

    assert await run_tick(factory, now=at(12), send=Outbox(), producers={KIND: busy}, config=CFG) == {"error": 1}


# ---------- 6. неправильный повод не убивает проход ----------


@pytest.mark.asyncio
async def test_mismatched_kind_is_rejected_others_still_go(db_session, factory) -> None:
    for key in (SASHA, KATYA):
        await seed_player(db_session, key, registered=at(10, day=1))
    mid = await seed_match(db_session, at(19, day=12))
    bad = Proposal(hn.Notice("brandnew", SASHA, mid, "чужой", []))
    good = await _proposal(db_session, KATYA)

    async def producer(session, *, now):
        return [bad, good]

    out = Outbox()
    counts = await run_tick(factory, now=at(12), send=out, producers={KIND: producer}, config=CFG, clock=lambda: at(12))
    assert [c for c, *_ in out.sent] == [KATYA] and counts["kind_mismatch"] == 1
    rows = (await db_session.execute(text("SELECT player_key, reason FROM kk_notify_decisions"))).all()
    assert (SASHA, "kind_mismatch") in [tuple(r) for r in rows]


# ---------- 9. gone ----------


class _Bot:
    def __init__(self, error) -> None:
        self.error = error

    async def send_message(self, **kw):
        raise self.error


@pytest.fixture
def sender(monkeypatch):
    async def fake_bot():
        return fake_bot.bot

    async def no_throttle():
        return None

    monkeypatch.setattr(hn, "_client_bot", fake_bot)
    monkeypatch.setattr(hn, "_throttle", no_throttle)
    return fake_bot


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "gone"),
    [
        ("Bad Request: chat not found", True),
        ("Bad Request: user is deactivated", True),
        ("Bad Request: message too long", False),
    ],
)
async def test_sender_gone_only_for_chat_not_found_and_deactivated(sender, message, gone) -> None:
    from aiogram.exceptions import TelegramBadRequest

    sender.bot = _Bot(TelegramBadRequest(method=None, message=message))
    assert await hn.send_via_client_bot(1, "t", []) == hn.FAILED  # прежний отправитель не меняется
    assert await hn.send_via_client_bot_gone(1, "t", []) == (hn.GONE if gone else hn.FAILED)


@pytest.mark.asyncio
async def test_gone_switches_player_off_in_new_path(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    out = Outbox(answer=hn.GONE)
    result = await _go(factory, await _proposal(db_session, SASHA), send=out)
    assert result.result == hn.BLOCKED
    again = await _go(factory, await _proposal(db_session, SASHA), send=out, now=at(15))
    assert again.reason == gate.BLOCKED and len(out.sent) == 1


@pytest.mark.asyncio
async def test_gone_switches_player_off_in_legacy_deliver(db_session, factory, monkeypatch) -> None:
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    notice = hn.Notice("nomove", SASHA, mid, "т", [])

    async def fake_due(session, *, now, overtakes=()):
        return [notice]

    monkeypatch.setattr(hn, "due_notices", fake_due)
    counts = await hn.deliver(factory, now=at(12), send=Outbox(answer=hn.GONE))
    assert counts["blocked"] == 1
    assert (await hn.get_prefs(db_session, SASHA))["blocked"] is True


# ---------- 13. отказ старого deliver — в журнал ----------


@pytest.mark.asyncio
async def test_legacy_refusal_is_journaled(db_session, factory, monkeypatch) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1), remind=False)
    mid = await seed_match(db_session, at(19, day=12))

    async def fake_due(session, *, now, overtakes=()):
        return [hn.Notice("nomove", SASHA, mid, "т", [])]

    monkeypatch.setattr(hn, "due_notices", fake_due)
    await hn.deliver(factory, now=at(12), send=Outbox())
    rows = (await db_session.execute(text("SELECT phase, kind, decision, reason FROM kk_notify_decisions"))).all()
    assert [tuple(r) for r in rows] == [("off", "nomove", "skip", "opted_out")]


# ---------- 10-12, 15. отчёт ----------

MONDAY = at(10, 0, day=16)


@pytest.mark.asyncio
async def test_report_counts_weekly_cap_refusals(db_session) -> None:
    await seed_player(db_session, SASHA)
    for day, reason in (
        (10, "weekly_cap"),
        (11, "weekly_cap"),
        (12, "daily_cap"),
        (3, "weekly_cap"),
        (17, "weekly_cap"),
    ):
        await db_session.execute(
            text(
                "INSERT INTO kk_notify_decisions (tick_at, player_key, phase, kind, decision, reason) "
                "VALUES (:t, :k, 'active', 'x', 'skip', :r)"
            ),
            {"t": at(12, day=day), "k": SASHA, "r": reason},
        )
    got = await report.collect(db_session, now=MONDAY)
    assert got.weekly_cap_refusals == 2
    assert "Записей журнала об отказе по недельному лимиту: 2 " in report.render_report(got, report.Thresholds())


@pytest.mark.asyncio
async def test_blocked_players_are_not_counted_as_delivery_failures(db_session) -> None:
    await seed_player(db_session, SASHA, blocked_at=at(5, day=12))
    await seed_player(db_session, KATYA)
    await seed_notice(db_session, SASHA, "result", None, failed=True, created_at=at(14, day=12))
    await seed_notice(db_session, KATYA, "result", None, failed=True, created_at=at(14, day=12))
    await seed_notice(db_session, KATYA, "nomove", None, failed=True, created_at=at(14, day=12))
    got = await report.collect(db_session, now=MONDAY)
    assert got.failed == {"result": 1, "nomove": 1}


@pytest.mark.asyncio
async def test_matches_in_week_counted_without_cancelled(db_session) -> None:
    await seed_match(db_session, at(19, day=10))
    await seed_match(db_session, at(19, day=16))  # после окна
    cancelled = await seed_match(db_session, at(19, day=11))
    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :m"), {"m": cancelled})
    assert (await report.collect(db_session, now=MONDAY)).matches_in_week == 1


@pytest.mark.asyncio
async def test_invite_pick_window_is_exactly_24_hours_after_send(db_session) -> None:
    sent = at(14, day=12)
    for key in (SASHA, KATYA, LESHA):
        await seed_player(db_session, key, registered=at(10, day=1))
        await seed_notice(db_session, key, "nomove", sent)
    await seed_pick(db_session, SASHA, sent + timedelta(hours=24))  # ровно сутки — входит
    await seed_pick(db_session, KATYA, sent + timedelta(hours=24, seconds=1))  # позже суток — нет
    await seed_pick(db_session, LESHA, sent - timedelta(seconds=1))  # до сообщения — нет
    got = await report.collect(db_session, now=MONDAY)
    assert got.invites["nomove"] == (3, 1)


@pytest.mark.asyncio
async def test_invite_window_ignores_immature_notices(db_session) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1))
    await seed_notice(db_session, SASHA, "nomove", at(23, 59, day=14))  # созрело: сутки прошли до конца окна
    await seed_notice(db_session, SASHA, "mfinal", at(12, day=15))  # суток после отправки до конца окна нет
    got = await report.collect(db_session, now=MONDAY)
    assert got.invites == {"nomove": (1, 0)}


@pytest.mark.asyncio
async def test_already_lost_player_is_not_counted_as_left(db_session) -> None:
    await seed_player(db_session, LESHA, registered=at(10, day=1, month=10))
    await seed_pick(db_session, LESHA, at(10, day=20, month=10))  # отвалился ещё до отчётной недели
    got = await report.collect(db_session, now=MONDAY)
    assert got.left == 0 and got.phases_now == {"lost": 1}


# ---------- A1. письма лиг не зависят от согласия remind ----------


@pytest.mark.asyncio
async def test_league_notice_ignores_remind_switch(db_session, factory) -> None:
    await seed_player(db_session, SASHA, remind=False)
    await _league_notice(db_session, SASHA)
    out = Outbox()
    await hn.deliver_league_notices(factory, now=at(12), send=out)
    assert len(out.sent) == 1  # как было всегда: remind — про игровую рассылку, не про письма лиги
    assert gate.KIND_POLICY["league"].respects_remind is False


@pytest.mark.asyncio
async def test_league_notice_still_waits_for_morning(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    await _league_notice(db_session, SASHA)
    out = Outbox()
    await hn.deliver_league_notices(factory, now=at(23, 30), send=out)
    assert out.sent == []


# ---------- A2. замок игрока в старом deliver и в письмах лиг ----------


async def _hold_lock(maker, key):
    """Соединение, которое держит замок игрока, пока не скажут отпустить."""
    release = asyncio.Event()
    held = asyncio.Event()

    async def hold():
        async with maker() as other:
            await gate.lock_player(other, key)
            held.set()
            await release.wait()
            await other.rollback()

    task = asyncio.create_task(hold())
    await held.wait()
    return release, task


@pytest.mark.asyncio
async def test_legacy_deliver_waits_for_player_lock(real, monkeypatch) -> None:
    notice = hn.Notice("nomove", REAL_KEY, real.match_ids[0], "т", [])

    async def fake_due(session, *, now, overtakes=()):
        return [notice]

    async def fake_scan(session, *, now):
        return []

    monkeypatch.setattr(hn, "due_notices", fake_due)
    monkeypatch.setattr(hn, "scan_league_ranks", fake_scan)
    today = datetime.now(MINSK_TZ).replace(hour=12, minute=0, second=0, microsecond=0)
    release, holder = await _hold_lock(real.factory, REAL_KEY)
    out = Outbox()
    work = asyncio.create_task(hn.deliver(real.factory, now=today, send=out))
    await asyncio.sleep(0.4)
    assert out.sent == [] and not work.done()  # ждёт замок
    release.set()
    await work
    await holder
    assert len(out.sent) == 1


@pytest.mark.asyncio
async def test_league_notices_wait_for_player_lock(real) -> None:
    async with real.factory() as s:
        league_id = (
            await s.execute(
                text("""INSERT INTO hockey_leagues (name, invite_code, owner_key, scope, term_kind, starts_at, ends_at)
                        VALUES ('Л', 'kk426real', :o, 'dinamo', 'month', :s, :e) RETURNING id"""),
                {"o": REAL_KEY, "s": at(0, day=1), "e": at(0, day=30)},
            )
        ).scalar_one()
        await s.execute(
            text("INSERT INTO hockey_league_notices (league_id, player_key, kind) VALUES (:l, :k, 'extended')"),
            {"l": league_id, "k": REAL_KEY},
        )
        await s.commit()
    try:
        release, holder = await _hold_lock(real.factory, REAL_KEY)
        out = Outbox()
        work = asyncio.create_task(hn.deliver_league_notices(real.factory, now=at(12), send=out))
        await asyncio.sleep(0.4)
        assert out.sent == [] and not work.done()
        release.set()
        await work
        await holder
        assert len(out.sent) == 1
    finally:
        async with real.factory() as s:
            await s.execute(text("DELETE FROM hockey_leagues WHERE invite_code = 'kk426real'"))
            await s.commit()


# ---------- A4. цикл матчей шлёт отправителем с обнаружением gone ----------


def test_loop_uses_gone_aware_sender_everywhere() -> None:
    import re

    src = (ROOT / "src/bot/notification_loops.py").read_text(encoding="utf-8")
    assert not re.search(r"send=send_via_client_bot\b(?!_gone)", src), "цикл вернулся к отправителю без gone"
    assert src.count("send=send_via_client_bot_gone") >= 3  # deliver, deliver_league_notices, kk_notify


# ---------- A5. чистка журнала ----------


@pytest.mark.asyncio
async def test_journal_cleanup_keeps_ninety_days(db_session, factory) -> None:
    now = at(12, day=16)
    for days_ago, label in ((91, "old"), (90, "edge"), (89, "keep"), (1, "new")):
        await db_session.execute(
            text(
                "INSERT INTO kk_notify_decisions (tick_at, player_key, phase, kind, decision, reason) "
                "VALUES (:t, 1, 'active', 'x', 'skip', :r)"
            ),
            {"t": now - timedelta(days=days_ago), "r": label},
        )
    await hn.cleanup_old_notices(factory, now=now, force=True)
    left = sorted(r.reason for r in (await db_session.execute(text("SELECT reason FROM kk_notify_decisions"))).all())
    assert left == ["edge", "keep", "new"]  # ровно 90 суток ещё хранится
