"""TASK-426: двенадцать гарантий системы уведомлений игрокам. Каждый тест падает, если гарантию нарушить.

Новый повод в тестах изображает ``before`` — вид, который строка ``hockey_notices`` ещё допускает (проверка
вида в базе ограничивает список; расширят её миграции срезов 2–4). В ``KIND_POLICY`` он временно становится
новым поводом с полным набором правил.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from kk_notify_helpers import (
    KATYA,
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

from src.application import hockey_notices as hn
from src.application import kk_notify, kk_notify_gate as gate
from src.application.kk_notify import Proposal, dispatch, match_still_open, run_tick
from src.application.kk_notify_gate import GateConfig, KindPolicy, admit

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


async def _proposal(db, key: int, *, recheck=None, starts=None) -> Proposal:
    mid = await seed_match(db, starts or at(19, day=12))
    return Proposal(hn.Notice(KIND, key, mid, "тест", [[{"text": "x", "callback_data": "y"}]]), recheck)


async def _go(factory, proposal, *, send, now=None, config=CFG, phase="active"):
    now = now or at(12)
    return await dispatch(
        factory, proposal, phase=phase, tick_at=now, send=send, config=config, clock=lambda: now
    )


async def _rows(db, sql: str, **params):
    return (await db.execute(text(sql), params)).all()


# ---------- 1. одно сообщение — не больше одного раза ----------


@pytest.mark.asyncio
async def test_g1_repeated_dispatch_sends_once(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    out = Outbox()
    first = await _go(factory, proposal, send=out)
    second = await _go(factory, proposal, send=out)
    assert (first.decision, first.result) == ("send", "ok")
    assert len(out.sent) == 1
    assert second.decision == "skip"  # дневной бюджет или «уже занято» — в любом случае второго нет


@pytest.mark.asyncio
async def test_g1_claim_row_exists_before_telegram_call(db_session, factory) -> None:
    """Рестарт посреди отправки: строка «занято» уже в базе к моменту вызова Telegram."""
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    seen: list[int] = []

    async def spy(chat_id, body, buttons):
        rows = await _rows(
            db_session, "SELECT 1 FROM hockey_notices WHERE player_key = :k AND kind = :kind", k=SASHA, kind=KIND
        )
        seen.append(len(rows))
        return "ok"

    await _go(factory, proposal, send=spy)
    assert seen == [1]


@pytest.mark.asyncio
async def test_g1_already_claimed_row_blocks_send(db_session, factory) -> None:
    """Другой цикл успел занять строку: этот не отправляет, даже если допуск пройден."""
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    await db_session.execute(
        text("INSERT INTO hockey_notices (player_key, match_id, kind, created_at) VALUES (:k, :m, :kind, :c)"),
        {"k": SASHA, "m": proposal.notice.match_id, "kind": KIND, "c": at(3, day=1)},  # давняя «занятая» строка
    )
    out = Outbox()
    result = await _go(factory, proposal, send=out)
    assert out.sent == [] and result.reason == "already_claimed"


# ---------- 2. единая точка допуска ----------


@pytest.mark.asyncio
async def test_g2_unregistered_kind_is_refused_everywhere(db_session, factory, monkeypatch) -> None:
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    ghost = hn.Notice("brandnew", SASHA, mid, "тест", [])
    assert (await admit(db_session, kind="brandnew", player_key=SASHA, now=at(12))).reason == gate.UNKNOWN_KIND

    out = Outbox()
    result = await _go(factory, Proposal(ghost), send=out)
    assert out.sent == [] and result.reason == gate.UNKNOWN_KIND

    # старый путь ``deliver`` тоже не пропускает неизвестное
    async def fake_due(session, *, now, overtakes=()):
        return [ghost]

    monkeypatch.setattr(hn, "due_notices", fake_due)
    counts = await hn.deliver(factory, now=at(12), send=out)
    assert out.sent == [] and counts.get("refused") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefs", "reason"),
    [
        ({"blocked_at": at(1, day=9)}, gate.BLOCKED),
        ({"remind": False}, gate.OPTED_OUT),
        ({"paused_until": at(12, day=20)}, gate.PAUSED),
    ],
)
async def test_g2_player_state_refusals(db_session, factory, prefs, reason) -> None:
    await seed_player(db_session, SASHA, **prefs)
    out = Outbox()
    result = await _go(factory, await _proposal(db_session, SASHA), send=out)
    assert out.sent == [] and result.reason == reason


@pytest.mark.asyncio
async def test_g2_pause_expires(db_session, factory) -> None:
    await seed_player(db_session, SASHA, paused_until=at(12))
    out = Outbox()
    await _go(factory, await _proposal(db_session, SASHA), send=out)
    assert len(out.sent) == 1  # пауза до 12:00 включительно закончилась ровно в 12:00


@pytest.mark.asyncio
async def test_g2_quiet_hours_boundaries(db_session) -> None:
    await seed_player(db_session, SASHA)

    async def ok(h, m):
        return (await admit(db_session, kind=KIND, player_key=SASHA, now=at(h, m), config=CFG)).allowed

    assert await ok(22, 59) and await ok(9, 0)
    assert not await ok(23, 0) and not await ok(8, 59) and not await ok(0, 0) and not await ok(3, 30)


@pytest.mark.asyncio
async def test_g2_daily_cap_counts_all_budgeted_kinds(db_session) -> None:
    await seed_player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "nomove", at(10, 0))  # прежний повод тоже съедает день
    result = await admit(db_session, kind=KIND, player_key=SASHA, now=at(15), config=CFG)
    assert (result.allowed, result.reason) == (False, gate.DAILY_LIMIT)


@pytest.mark.asyncio
async def test_g2_results_and_events_do_not_spend_budget(db_session) -> None:
    await seed_player(db_session, SASHA)
    for kind in ("result", "moved", "rescore", "mvfree"):
        await seed_notice(db_session, SASHA, kind, at(10, 0))
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(15), config=CFG)).allowed


@pytest.mark.asyncio
async def test_g2_weekly_cap(db_session) -> None:
    await seed_player(db_session, SASHA)
    for days_ago in (5, 3, 1):
        await seed_notice(db_session, SASHA, "nomove", at(12, day=10 - days_ago))
    result = await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)
    assert (result.allowed, result.reason) == (False, gate.WEEKLY_LIMIT)


@pytest.mark.asyncio
async def test_g2_type_off_and_legacy_weekly_not_applied(db_session) -> None:
    """Прежние ``nomove``/``mfinal``/``overtook`` недельным лимитом не режутся (поведение сохранено), отключение типа действует."""
    await seed_player(db_session, SASHA, notify_nomove=False)
    assert (await admit(db_session, kind="nomove", player_key=SASHA, now=at(12))).reason == gate.TYPE_OFF
    await seed_player(db_session, KATYA)
    for days_ago in (5, 3, 1):
        await seed_notice(db_session, KATYA, "mfinal", at(12, day=10 - days_ago))
    assert (await admit(db_session, kind="nomove", player_key=KATYA, now=at(12))).allowed


def test_g2_no_sender_bypasses_the_gate() -> None:
    """Трипвайр: к Telegram-отправке игроку ведут только известные места. Новый путь — осознанная правка этого списка."""
    allowed = {"src/application/hockey_notices.py", "src/bot/notification_loops.py", "src/application/kk_notify.py"}
    found = set()
    for path in (ROOT / "src").rglob("*.py"):
        body = path.read_text(encoding="utf-8")
        if "send_via_client_bot" in body or "hockey_notices.send_via" in body:
            found.add(str(path.relative_to(ROOT)))
    assert found <= allowed, f"новый отправитель вне допуска: {found - allowed}"
    kk = (ROOT / "src/application/kk_notify.py").read_text(encoding="utf-8")
    assert "admit(" in kk and kk.index("admit(") < kk.index("await send("), "dispatch обязан звать допуск до отправки"
    deliver_src = (ROOT / "src/application/hockey_notices.py").read_text(encoding="utf-8")
    body = deliver_src[deliver_src.index("async def deliver(") : deliver_src.index("# ---------- ход и")]
    assert body.index("await admit(") < body.index("await send("), "deliver обязан звать допуск до отправки"


# ---------- 3. закрыто по умолчанию ----------


@pytest.mark.asyncio
async def test_g3_gate_error_means_no_send(db_session, factory, monkeypatch) -> None:
    await seed_player(db_session, SASHA)

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(gate, "_spent", boom)
    out = Outbox()
    result = await _go(factory, await _proposal(db_session, SASHA), send=out)
    assert out.sent == [] and result.reason.startswith(gate.ERROR_PREFIX)


@pytest.mark.asyncio
async def test_g3_one_player_failing_does_not_stop_others(db_session, factory, monkeypatch) -> None:
    for key in (SASHA, KATYA):
        await seed_player(db_session, key, registered=at(10, day=1))
        await seed_pick(db_session, key, at(10, day=9))
    proposals = [await _proposal(db_session, SASHA), await _proposal(db_session, KATYA)]

    async def producer(session, *, now):
        return proposals

    real_phase = kk_notify.PlayerFacts.phase

    def phase(self, now):
        if self.player_key == SASHA:
            raise ValueError("bad phase")
        return real_phase(self, now)

    monkeypatch.setattr(kk_notify.PlayerFacts, "phase", phase)
    out = Outbox()
    counts = await run_tick(factory, now=at(12), send=out, producers={KIND: producer}, config=CFG, clock=lambda: at(12))
    assert [chat for chat, *_ in out.sent] == [KATYA]
    assert counts.get("error") == 1
    journal = await _rows(db_session, "SELECT player_key, decision, reason FROM kk_notify_decisions ORDER BY player_key")
    assert (SASHA, "error", "tick") in [tuple(r) for r in journal]


@pytest.mark.asyncio
async def test_g3_send_exception_is_failure_not_crash(db_session, factory) -> None:
    await seed_player(db_session, SASHA)

    async def raising(*a):
        raise RuntimeError("boom")

    result = await _go(factory, await _proposal(db_session, SASHA), send=raising)
    assert (result.decision, result.result) == ("send", "failed")


@pytest.mark.asyncio
async def test_g3_broken_producer_is_isolated(db_session, factory) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1))
    good = await _proposal(db_session, SASHA)

    async def bad(session, *, now):
        raise RuntimeError("nope")

    async def fine(session, *, now):
        return [good]

    monkey_kinds = frozenset({KIND, "mfinal"})
    cfg = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=monkey_kinds)
    out = Outbox()
    counts = await run_tick(
        factory, now=at(12), send=out, producers={"mfinal": bad, KIND: fine}, config=cfg, clock=lambda: at(12)
    )
    assert len(out.sent) == 1 and counts["producer_errors"] == 1


# ---------- 4. проверка перед самой отправкой ----------


@pytest.mark.asyncio
async def test_g4_pick_made_after_candidate_built(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    proposal = Proposal(hn.Notice(KIND, SASHA, mid, "т", []), match_still_open(mid))
    await seed_pick(db_session, SASHA, at(11, 59), match_id=mid)  # ход сделан уже после сборки кандидата
    out = Outbox()
    result = await _go(factory, proposal, send=out)
    assert out.sent == [] and result.reason == "stale:has_pick"


@pytest.mark.asyncio
async def test_g4_match_started_or_closed(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(12, 0, day=10))
    proposal = Proposal(hn.Notice(KIND, SASHA, mid, "т", []), match_still_open(mid))
    out = Outbox()
    assert (await _go(factory, proposal, send=out, now=at(11, 59))).reason == "stale:match_started"  # закрытие за минуту
    assert (await _go(factory, proposal, send=out, now=at(12, 30))).reason == "stale:match_started"
    await db_session.execute(text("UPDATE hockey_matches SET status = 'cancelled' WHERE id = :m"), {"m": mid})
    assert (await _go(factory, proposal, send=out, now=at(10))).reason == "stale:match_status"
    assert out.sent == []


@pytest.mark.asyncio
async def test_g4_player_switched_off_after_candidate_built(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    await seed_player(db_session, SASHA, remind=False)  # нажал «не присылать», пока кандидат ждал в списке
    out = Outbox()
    assert (await _go(factory, proposal, send=out)).reason == gate.OPTED_OUT
    assert out.sent == []


@pytest.mark.asyncio
async def test_g4_fresh_candidate_passes(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    out = Outbox()
    await _go(factory, Proposal(hn.Notice(KIND, SASHA, mid, "т", []), match_still_open(mid)), send=out)
    assert len(out.sent) == 1


# ---------- 5. выключатели ----------


def test_g5_defaults_are_closed(monkeypatch) -> None:
    for name in ("KK_NOTIFY_ENABLED", "KK_NOTIFY_DRY_RUN", "KK_NOTIFY_TEXTS_ACCEPTED", "KK_NOTIFY_KINDS", "KK_NOTIFY_WHITELIST"):
        monkeypatch.delenv(name, raising=False)
    cfg = GateConfig.from_settings()
    assert (cfg.enabled, cfg.dry_run, cfg.texts_accepted) == (False, True, False)
    assert cfg.kinds == frozenset() and cfg.whitelist == frozenset()


def test_g5_flags_come_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("KK_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("KK_NOTIFY_DRY_RUN", "0")
    monkeypatch.setenv("KK_NOTIFY_KINDS", "nomove_today, comeback")
    monkeypatch.setenv("KK_NOTIFY_WHITELIST", "11, 22,x")
    cfg = GateConfig.from_settings()
    assert cfg.enabled and not cfg.dry_run
    assert cfg.kinds == {"nomove_today", "comeback"} and cfg.whitelist == {11, 22}


@pytest.mark.asyncio
async def test_g5_master_flag_off_sends_nothing(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    out = Outbox()
    result = await _go(factory, await _proposal(db_session, SASHA), send=out, config=GateConfig(kinds=frozenset({KIND})))
    assert out.sent == [] and result.reason == gate.DISABLED
    # и проход целиком молчит, пока общий флаг выключен
    assert await run_tick(factory, now=at(12), send=out, producers={KIND: None}, config=GateConfig()) == {}


@pytest.mark.asyncio
async def test_g5_kind_flag_off_sends_nothing(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    out = Outbox()
    cfg = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({"other"}))
    result = await _go(factory, await _proposal(db_session, SASHA), send=out, config=cfg)
    assert out.sent == [] and result.reason == gate.KIND_OFF


@pytest.mark.asyncio
async def test_g5_dry_run_logs_but_neither_sends_nor_claims(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    cfg = GateConfig(enabled=True, dry_run=True, texts_accepted=True, kinds=frozenset({KIND}))
    out = Outbox()
    result = await _go(factory, await _proposal(db_session, SASHA), send=out, config=cfg)
    assert out.sent == [] and (result.decision, result.reason) == ("dry_run", gate.DRY_RUN)
    assert await _rows(db_session, "SELECT 1 FROM hockey_notices WHERE kind = :k", k=KIND) == []
    journal = await _rows(db_session, "SELECT decision, kind FROM kk_notify_decisions")
    assert [tuple(r) for r in journal] == [("dry_run", KIND)]


@pytest.mark.asyncio
async def test_g5_dry_run_still_applies_limits(db_session, factory) -> None:
    """«Что бы отправили» не врёт: правила допуска в сухом прогоне те же."""
    await seed_player(db_session, SASHA)
    cfg = GateConfig(enabled=True, dry_run=True, texts_accepted=True, kinds=frozenset({KIND}))
    result = await _go(factory, await _proposal(db_session, SASHA), send=Outbox(), config=cfg, now=at(23, 30))
    assert (result.decision, result.reason) == ("skip", gate.QUIET)


# ---------- 6. тексты не выходят без принятия ----------


@pytest.mark.asyncio
async def test_g6_without_acceptance_only_whitelist_gets_messages(db_session, factory) -> None:
    for key in (SASHA, KATYA):
        await seed_player(db_session, key)
    cfg = GateConfig(enabled=True, dry_run=False, texts_accepted=False, kinds=frozenset({KIND}), whitelist=frozenset({SASHA}))
    out = Outbox()
    r1 = await _go(factory, await _proposal(db_session, SASHA), send=out, config=cfg)
    r2 = await _go(factory, await _proposal(db_session, KATYA), send=out, config=cfg)
    assert [chat for chat, *_ in out.sent] == [SASHA]
    assert (r1.decision, r2.reason) == ("send", gate.TEXTS_NOT_ACCEPTED)


@pytest.mark.asyncio
async def test_g6_with_acceptance_everyone_is_admitted(db_session, factory) -> None:
    await seed_player(db_session, KATYA)
    out = Outbox()
    await _go(factory, await _proposal(db_session, KATYA), send=out)
    assert len(out.sent) == 1


# ---------- 7. журнал решений ----------


@pytest.mark.asyncio
async def test_g7_journal_answers_why_sent_or_not(db_session, factory) -> None:
    await seed_player(db_session, SASHA, registered=at(10, day=1))
    await seed_pick(db_session, SASHA, at(10, day=9))
    await seed_player(db_session, KATYA, registered=at(10, day=1), remind=False)
    proposals = [await _proposal(db_session, SASHA), await _proposal(db_session, KATYA)]

    async def producer(session, *, now):
        return proposals

    out = Outbox()
    await run_tick(factory, now=at(12), send=out, producers={KIND: producer}, config=CFG, clock=lambda: at(12))
    rows = {
        r.player_key: tuple(r)[1:]
        for r in await _rows(
            db_session, "SELECT player_key, phase, kind, decision, reason, result FROM kk_notify_decisions"
        )
    }
    assert rows[SASHA] == ("active", KIND, "send", None, "ok")
    assert rows[KATYA] == ("off", KIND, "skip", gate.OPTED_OUT, None)


@pytest.mark.asyncio
async def test_g7_repeated_refusal_is_not_rewritten_within_hour(db_session, factory) -> None:
    await seed_player(db_session, SASHA, remind=False)
    proposal = await _proposal(db_session, SASHA)
    for minute in (0, 10, 20):
        await _go(factory, proposal, send=Outbox(), now=at(12, minute))
    assert len(await _rows(db_session, "SELECT 1 FROM kk_notify_decisions")) == 1
    await _go(factory, proposal, send=Outbox(), now=at(13, 30))
    assert len(await _rows(db_session, "SELECT 1 FROM kk_notify_decisions")) == 2


# ---------- 8. ошибки Telegram ----------


@pytest.mark.asyncio
async def test_g8_temporary_failure_releases_and_stops_after_limit(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    out = Outbox(answer=hn.RETRY)
    results = []
    for _ in range(hn.MAX_ATTEMPTS + 3):
        results.append((await _go(factory, proposal, send=out)).result)
    assert results[: hn.MAX_ATTEMPTS - 1] == [hn.RETRY] * (hn.MAX_ATTEMPTS - 1)
    assert results[hn.MAX_ATTEMPTS - 1] == hn.FAILED  # лимит исчерпан — окончательный сбой
    assert len(out.sent) == hn.MAX_ATTEMPTS  # дальше ни одной попытки: нет шторма
    [row] = await _rows(db_session, "SELECT sent_at, failed FROM hockey_notices WHERE kind = :k", k=KIND)
    assert row.sent_at is None and row.failed is True


@pytest.mark.asyncio
async def test_g8_released_row_is_retried_next_pass(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    await _go(factory, proposal, send=Outbox(answer=hn.RETRY))
    assert await _rows(db_session, "SELECT 1 FROM hockey_notices WHERE kind = :k", k=KIND) == []
    out = Outbox()
    assert (await _go(factory, proposal, send=out)).result == "ok" and len(out.sent) == 1


@pytest.mark.asyncio
async def test_g8_blocked_switches_player_off_and_never_retries(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    out = Outbox(answer=hn.BLOCKED)
    assert (await _go(factory, await _proposal(db_session, SASHA), send=out)).result == hn.BLOCKED
    prefs = await _rows(db_session, "SELECT bot_blocked_at FROM hockey_player_prefs WHERE player_key = :k", k=SASHA)
    assert prefs[0].bot_blocked_at is not None
    again = await _go(factory, await _proposal(db_session, SASHA), send=out, now=at(12, 30))
    assert again.reason == gate.BLOCKED and len(out.sent) == 1


@pytest.mark.asyncio
async def test_g8_permanent_failure_is_not_repeated(db_session, factory) -> None:
    await seed_player(db_session, SASHA)
    proposal = await _proposal(db_session, SASHA)
    out = Outbox(answer=hn.FAILED)
    await _go(factory, proposal, send=out)
    await _go(factory, proposal, send=out, now=at(15))
    assert len(out.sent) == 1


# ---------- 9. время ----------


@pytest.mark.asyncio
async def test_g9_day_is_minsk_day_not_utc(db_session) -> None:
    await seed_player(db_session, SASHA)
    # 22:30 UTC 9 ноября = 01:30 по Минску 10 ноября: это уже сегодняшний день
    from datetime import datetime, timezone

    await seed_notice(db_session, SASHA, "nomove", datetime(2026, 11, 9, 22, 30, tzinfo=timezone.utc))
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_g9_day_boundary(db_session) -> None:
    await seed_player(db_session, SASHA)
    await seed_notice(db_session, SASHA, "nomove", at(23, 59, day=9))  # вчера по Минску
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(9, 0), config=CFG)).allowed
    await seed_notice(db_session, SASHA, "mfinal", at(0, 0))  # ровно полночь — уже сегодня
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(9, 0), config=CFG)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_g9_week_boundary(db_session) -> None:
    await seed_player(db_session, SASHA)
    # окно недели: 10 ноября и шесть дней до него, то есть с 4 ноября 00:00
    await seed_notice(db_session, SASHA, "nomove", at(23, 59, day=3))  # за границей окна
    await seed_notice(db_session, SASHA, "mfinal", at(12, day=5))
    await seed_notice(db_session, SASHA, "overtook", at(12, day=7))
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)).allowed
    await seed_notice(db_session, SASHA, "nomove", at(0, 0, day=4))  # первая минута окна
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12), config=CFG)).reason == gate.WEEKLY_LIMIT


@pytest.mark.asyncio
async def test_g9_week_across_month_end(db_session) -> None:
    await seed_player(db_session, SASHA)
    for day in (28, 29, 30):
        await seed_notice(db_session, SASHA, "nomove", at(12, day=day, month=11))
    now = at(12, day=1, month=12)
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=now, config=CFG)).reason == gate.WEEKLY_LIMIT
    # 4 декабря окно ещё начинается 28 ноября; 5 декабря 28-е вышло из окна и остались два сообщения
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12, day=4, month=12), config=CFG)).reason == gate.WEEKLY_LIMIT
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12, day=5, month=12), config=CFG)).allowed


def test_g9_quiet_hours_use_minsk_not_utc() -> None:
    from datetime import datetime, timezone

    assert gate.in_quiet_hours(datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc))  # 23:00 Минск
    assert not gate.in_quiet_hours(datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc))  # 09:00 Минск
    assert gate.in_quiet_hours(datetime(2026, 11, 10, 5, 59, tzinfo=timezone.utc))


@pytest.mark.asyncio
async def test_g9_admission_reads_the_clock_at_send_time(db_session, factory) -> None:
    """Проход начался днём, а к отправке уже 23:00: тихие часы смотрят на часы отправки, не на начало прохода."""
    await seed_player(db_session, SASHA)
    out = Outbox()
    result = await dispatch(
        factory,
        await _proposal(db_session, SASHA),
        phase="active",
        tick_at=at(12),
        send=out,
        config=CFG,
        clock=lambda: at(23, 0),
    )
    assert out.sent == [] and result.reason == gate.QUIET


# ---------- 10. обратимость ----------


def test_g10_migration_only_adds() -> None:
    src = (ROOT / "migrations/versions/0327_kk_notify_journal.py").read_text(encoding="utf-8")
    upgrade = src[src.index("def upgrade") : src.index("def downgrade")]
    for forbidden in ("drop_", "DROP", "DELETE", "alter_column", "execute("):
        assert forbidden not in upgrade, forbidden


@pytest.mark.asyncio
async def test_g10_any_kind_can_be_switched_off_without_release(db_session, factory, monkeypatch) -> None:
    await seed_player(db_session, SASHA)
    monkeypatch.setenv("KK_NOTIFY_ENABLED", "1")
    monkeypatch.setenv("KK_NOTIFY_DRY_RUN", "0")
    monkeypatch.setenv("KK_NOTIFY_TEXTS_ACCEPTED", "1")
    monkeypatch.setenv("KK_NOTIFY_KINDS", KIND)
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12))).allowed
    monkeypatch.setenv("KK_NOTIFY_KINDS", "")  # только переменная окружения
    assert (await admit(db_session, kind=KIND, player_key=SASHA, now=at(12))).reason == gate.KIND_OFF


# ---------- 11. данные игрока ----------


@pytest.mark.asyncio
async def test_g11_journal_holds_no_personal_data(db_session, factory) -> None:
    cols = await _rows(
        db_session,
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'kk_notify_decisions'",
    )
    assert {c.column_name for c in cols} == {
        "id", "tick_at", "player_key", "phase", "kind", "decision", "reason", "result", "created_at",
    }  # fmt: skip
    await seed_player(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    secret = "Секретное Имя Соперника 777"
    await _go(factory, Proposal(hn.Notice(KIND, SASHA, mid, f"<b>{secret}</b>", [])), send=Outbox())
    dump = await _rows(db_session, "SELECT t::text FROM kk_notify_decisions AS t")
    assert dump and all(secret not in row[0] for row in dump)


# ---------- 2 (продолжение). один повод на игрока за проход ----------


@pytest.mark.asyncio
async def test_g2_one_message_per_player_per_tick_by_priority(db_session, factory, monkeypatch) -> None:
    """Два кандидата на одного игрока в проходе: уходит важнейший, второй не уходит."""
    monkeypatch.setitem(gate.KIND_POLICY, "mfinal", KindPolicy(budgeted=True, weekly=True, new=True, priority=1))
    await seed_player(db_session, SASHA, registered=at(10, day=1))
    low = await _proposal(db_session, SASHA)
    mid = await seed_match(db_session, at(19, day=12))
    high = Proposal(hn.Notice("mfinal", SASHA, mid, "важный", []))

    async def p_low(session, *, now):
        return [low]

    async def p_high(session, *, now):
        return [high]

    cfg = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({KIND, "mfinal"}))
    out = Outbox()
    await run_tick(factory, now=at(12), send=out, producers={KIND: p_low, "mfinal": p_high}, config=cfg, clock=lambda: at(12))
    assert [body for _, body, _ in out.sent] == ["важный"]
