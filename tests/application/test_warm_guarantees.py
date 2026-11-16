"""TASK-428: гарантии прогрева посетителей. Каждый тест падает, если гарантию нарушить.

Допуск один на человека (``kk_notify_gate``): бюджет общий с игрой и колокольчиком катка, тихие часы, «Не присылать»,
блокировка, флаги ``WARM_*``, сухой прогон, белый список; «занято» до вызова Telegram, замок, журнал.
"""

from __future__ import annotations

import pytest
from kk_notify_helpers import Outbox, make_factory, seed_notice, seed_player
from sqlalchemy import text
from warm_helpers import (
    ANNA,
    BORIS,
    at,
    seed_arena,
    seed_delivery,
    seed_warm_notice,
    seed_warm_prefs,
    seed_watch,
)

from src.application import hockey_notices as hn
from src.application import kk_notify
from src.application import kk_notify_gate as gate
from src.application import warm_notify as wn
from src.application.kk_notify import HOCKEY_STORE, Proposal, dispatch
from src.application.kk_notify_gate import FAMILY_WARM, GateConfig, admit
from src.shared.config import Settings

KINDS = frozenset(gate.WARM_KINDS)
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=KINDS, family=FAMILY_WARM)
KK_CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=frozenset({"invite"}))


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    hn._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


def _notice(key: int, kind: str = gate.KIND_WARM_TODAY, ref: str = "d2026-11-19") -> wn.WarmNotice:
    return wn.WarmNotice(kind, key, ref, "Сегодня на катке «Чижовка» лёд в 19:30.", [[wn.off_button()]], None)


async def _go(factory, notice, *, send, now=None, config=CFG, store=wn.WARM_STORE, recheck=None):
    now = now or at(10)
    return await dispatch(
        factory,
        Proposal(notice, recheck),
        phase="subscriber",
        tick_at=now,
        send=send,
        config=config,
        clock=lambda: now,
        store=store,
    )


async def _ok(db, key: int, *, now=None, kind: str = gate.KIND_WARM_TODAY, config=CFG):
    return await admit(db, kind=kind, player_key=key, now=now or at(12), config=config)


# ---------- 1. закрыто по умолчанию ----------


def test_defaults_are_closed() -> None:
    cfg = GateConfig.from_settings(Settings(), family=FAMILY_WARM)  # type: ignore[call-arg]
    assert (cfg.enabled, cfg.dry_run, cfg.texts_accepted, cfg.kinds, cfg.whitelist) == (
        False,
        True,
        False,
        frozenset(),
        frozenset(),
    )
    assert cfg.family == FAMILY_WARM


@pytest.mark.parametrize("raw", ["", "dry", "1", "true", "on"])
def test_dry_run_turns_off_only_explicitly(monkeypatch, raw) -> None:
    monkeypatch.setenv("WARM_DRY_RUN", raw)
    assert GateConfig.from_settings(Settings(), family=FAMILY_WARM).dry_run is True  # type: ignore[call-arg]
    monkeypatch.setenv("WARM_DRY_RUN", "0")
    assert GateConfig.from_settings(Settings(), family=FAMILY_WARM).dry_run is False  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_run_tick_with_default_settings_reads_nothing_sends_nothing(factory) -> None:
    called: list[str] = []

    async def producer(session, *, now):
        called.append("x")
        return [Proposal(_notice(ANNA))]

    out = Outbox()
    counts = await wn.run_tick(factory, now=at(10), send=out, producers={gate.KIND_WARM_TODAY: producer})
    assert counts == {} and called == [] and out.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cfg", "reason"),
    [
        (GateConfig(family=FAMILY_WARM), gate.DISABLED),
        (GateConfig(enabled=True, dry_run=False, texts_accepted=True, family=FAMILY_WARM), gate.KIND_OFF),
        (GateConfig(enabled=True, dry_run=False, kinds=KINDS, family=FAMILY_WARM), gate.TEXTS_NOT_ACCEPTED),
        (KK_CFG, gate.FAMILY_MISMATCH),  # выключатели игры прогрев не открывают
    ],
)
async def test_switches(db_session, cfg, reason) -> None:
    result = await _ok(db_session, ANNA, config=cfg)
    assert (result.allowed, result.reason) == (False, reason)


@pytest.mark.asyncio
async def test_whitelist_passes_before_texts_accepted(db_session) -> None:
    cfg = GateConfig(enabled=True, dry_run=False, kinds=KINDS, whitelist=frozenset({ANNA}), family=FAMILY_WARM)
    assert (await _ok(db_session, ANNA, config=cfg)).allowed
    assert (await _ok(db_session, BORIS, config=cfg)).reason == gate.TEXTS_NOT_ACCEPTED


@pytest.mark.asyncio
async def test_dry_run_writes_journal_and_sends_nothing(db_session, factory) -> None:
    out = Outbox()
    cfg = GateConfig(enabled=True, dry_run=True, kinds=KINDS, family=FAMILY_WARM)
    result = await _go(factory, _notice(ANNA), send=out, config=cfg)
    assert out.sent == [] and (result.decision, result.reason) == ("dry_run", gate.DRY_RUN)
    rows = (
        await db_session.execute(
            text("SELECT phase, kind, decision FROM kk_notify_decisions WHERE player_key = :k"), {"k": ANNA}
        )
    ).all()
    assert [tuple(r) for r in rows] == [("subscriber", gate.KIND_WARM_TODAY, "dry_run")]
    claimed = (await db_session.execute(text("SELECT 1 FROM warm_notices WHERE telegram_id = :k"), {"k": ANNA})).all()
    assert claimed == []  # сухой прогон ничего не занимает


# ---------- 2. общий бюджет с игрой и колокольчиком ----------


@pytest.mark.asyncio
async def test_game_message_today_spends_warm_day(db_session) -> None:
    await seed_player(db_session, ANNA)
    await seed_notice(db_session, ANNA, "nomove", at(9, 30))
    assert (await _ok(db_session, ANNA)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_warm_message_today_spends_game_day(db_session) -> None:
    await seed_player(db_session, ANNA, remind=True)
    await db_session.execute(
        text("UPDATE hockey_player_prefs SET notify_consent = true WHERE player_key = :k"), {"k": ANNA}
    )
    await seed_warm_notice(db_session, ANNA, gate.KIND_WARM_TODAY, at(9, 30))
    for kind, cfg in (("nomove", None), ("invite", KK_CFG)):
        result = await admit(db_session, kind=kind, player_key=ANNA, now=at(15), config=cfg)
        assert (result.allowed, result.reason) == (False, gate.DAILY_LIMIT), kind


@pytest.mark.asyncio
async def test_claimed_but_unsent_warm_counts(db_session) -> None:
    """Строка «занято» без отправки (в пути) тоже тратит день: два цикла не отправят двоих."""
    await seed_warm_notice(db_session, ANNA, gate.KIND_WARM_WELCOME, None, created_at=at(9, 1))
    assert (await _ok(db_session, ANNA)).reason == gate.DAILY_LIMIT
    # окончательно не ушедшее (failed) день не тратит
    await seed_warm_notice(db_session, BORIS, gate.KIND_WARM_WELCOME, None, created_at=at(9, 1), failed=True)
    assert (await _ok(db_session, BORIS)).allowed


@pytest.mark.asyncio
async def test_ice_watch_delivery_counts_in_budget(db_session) -> None:
    arena = await seed_arena(db_session)
    watch = await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_delivery(db_session, watch, at(9, 15), ok=False)  # недоставленное не считается
    assert (await _ok(db_session, ANNA)).allowed
    await seed_delivery(db_session, watch, at(9, 20))
    assert (await _ok(db_session, ANNA)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_season_open_reminder_counts_in_budget(db_session) -> None:
    arena = await seed_arena(db_session)
    watch = await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1), kind="season_open", active=False)
    await db_session.execute(
        text("UPDATE client_ice_watches SET last_notified_at = :t WHERE id = :w"), {"t": at(9, 5), "w": watch}
    )
    assert (await _ok(db_session, ANNA)).reason == gate.DAILY_LIMIT


@pytest.mark.asyncio
async def test_weekly_cap_is_shared(db_session) -> None:
    await seed_player(db_session, ANNA)
    arena = await seed_arena(db_session)
    watch = await seed_watch(db_session, ANNA, arena, created_at=at(10, day=1))
    await seed_notice(db_session, ANNA, "nomove", at(12, day=13))
    await seed_warm_notice(db_session, ANNA, gate.KIND_WARM_WEEK, at(10, day=15))
    await seed_delivery(db_session, watch, at(12, day=17))
    result = await _ok(db_session, ANNA)
    assert (result.allowed, result.reason) == (False, gate.WEEKLY_LIMIT)
    # неделя скользящая: через сутки после выпадения первой записи снова можно
    assert (await _ok(db_session, ANNA, now=at(12, day=20))).allowed


@pytest.mark.asyncio
async def test_game_results_still_outside_budget(db_session) -> None:
    await seed_player(db_session, ANNA)
    await seed_notice(db_session, ANNA, "result", at(9, 30))
    assert (await _ok(db_session, ANNA)).allowed


# ---------- 3. тихие часы ----------


@pytest.mark.asyncio
async def test_quiet_hours_boundaries(db_session) -> None:
    async def ok(h, m):
        return (await _ok(db_session, ANNA, now=at(h, m))).allowed

    assert await ok(9, 0) and await ok(22, 59)
    assert not await ok(23, 0) and not await ok(8, 59) and not await ok(3, 0)


# ---------- 4. «Не присылать» и блокировка ----------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", gate.WARM_KINDS)
async def test_opt_out_stops_every_warm_kind(db_session, kind) -> None:
    await wn.set_opt_out(db_session, ANNA, True, now=at(9))
    assert (await _ok(db_session, ANNA, kind=kind)).reason == gate.OPTED_OUT
    await wn.set_opt_out(db_session, ANNA, False)
    assert (await _ok(db_session, ANNA, kind=kind)).allowed


@pytest.mark.asyncio
async def test_blocked_by_warm_or_by_game(db_session) -> None:
    await seed_warm_prefs(db_session, ANNA, bot_blocked_at=at(9))
    assert (await _ok(db_session, ANNA)).reason == gate.BLOCKED
    await seed_player(db_session, BORIS, blocked_at=at(9))  # бота заблокировали — замечено игрой
    assert (await _ok(db_session, BORIS)).reason == gate.BLOCKED


@pytest.mark.asyncio
async def test_blocked_answer_switches_person_off(db_session, factory) -> None:
    out = Outbox(answer="blocked")
    result = await _go(factory, _notice(ANNA), send=out)
    assert result.result == hn.BLOCKED
    row = (
        await db_session.execute(text("SELECT bot_blocked_at FROM warm_prefs WHERE telegram_id = :k"), {"k": ANNA})
    ).one()
    assert row.bot_blocked_at is not None
    second = await _go(factory, _notice(ANNA, ref="d2026-11-20"), send=out, now=at(10, day=20))
    assert second.reason == gate.BLOCKED and len(out.sent) == 1


@pytest.mark.asyncio
async def test_gone_chat_is_treated_as_blocked(db_session, factory) -> None:
    result = await _go(factory, _notice(ANNA), send=Outbox(answer="gone"))
    assert result.result == hn.BLOCKED


# ---------- 5. «занято» до отправки, замок, повтор ----------


@pytest.mark.asyncio
async def test_claim_row_exists_before_telegram_call(db_session, factory) -> None:
    seen: list[int] = []

    async def spy(chat_id, body, buttons):
        rows = (
            await db_session.execute(
                text("SELECT 1 FROM warm_notices WHERE telegram_id = :k AND sent_at IS NULL"), {"k": ANNA}
            )
        ).all()
        seen.append(len(rows))
        return "ok"

    result = await _go(factory, _notice(ANNA), send=spy)
    assert seen == [1] and result.result == hn.SENT


@pytest.mark.asyncio
async def test_rerun_never_duplicates(db_session, factory) -> None:
    out = Outbox()
    first = await _go(factory, _notice(ANNA, kind=gate.KIND_WARM_NUDGE, ref="once"), send=out)
    # даже на следующей неделе, когда бюджет свободен, разовое напоминание второй раз не уходит
    second = await _go(factory, _notice(ANNA, kind=gate.KIND_WARM_NUDGE, ref="once"), send=out, now=at(10, day=28))
    assert first.result == hn.SENT and second.reason == "already_claimed" and len(out.sent) == 1


@pytest.mark.asyncio
async def test_retry_releases_claim_and_failed_stays(db_session, factory) -> None:
    out = Outbox(answer="retry")
    await _go(factory, _notice(ANNA), send=out)
    left = (await db_session.execute(text("SELECT 1 FROM warm_notices WHERE telegram_id = :k"), {"k": ANNA})).all()
    assert left == []  # временный сбой: строка освобождена, повторим на следующем проходе
    await _go(factory, _notice(ANNA), send=Outbox(answer="failed"))
    row = (await db_session.execute(text("SELECT failed FROM warm_notices WHERE telegram_id = :k"), {"k": ANNA})).one()
    assert row.failed is True


@pytest.mark.asyncio
async def test_lock_taken_on_same_key_as_game_before_admission(factory, monkeypatch) -> None:
    order: list[str] = []
    real_lock, real_admit = kk_notify.lock_player, kk_notify.admit

    async def lock(session, key):
        order.append(f"lock:{key}")
        await real_lock(session, key)

    async def admit_spy(session, **kw):
        order.append("admit")
        return await real_admit(session, **kw)

    monkeypatch.setattr(kk_notify, "lock_player", lock)
    monkeypatch.setattr(kk_notify, "admit", admit_spy)
    await _go(factory, _notice(ANNA), send=Outbox())
    assert order[:2] == [f"lock:{ANNA}", "admit"]
    # ключ замка один для игры и прогрева: оба пути сериализуются по человеку
    assert gate._LOCK.text.count("hashtextextended") == 1


@pytest.mark.asyncio
async def test_warm_notice_cannot_use_game_store(db_session, factory) -> None:
    out = Outbox()
    result = await _go(factory, _notice(ANNA), send=out, store=HOCKEY_STORE)
    assert out.sent == [] and result.reason == "store_mismatch"


@pytest.mark.asyncio
async def test_stale_recheck_blocks_send(db_session, factory) -> None:
    async def stale(session, key, now):
        return "no_subscription"

    out = Outbox()
    result = await _go(factory, _notice(ANNA), send=out, recheck=stale)
    assert out.sent == [] and result.reason == "stale:no_subscription"


@pytest.mark.asyncio
async def test_gate_error_refuses(db_session, monkeypatch) -> None:
    async def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(gate, "_limits", boom)
    result = await _ok(db_session, ANNA)
    assert not result.allowed and result.reason.startswith(gate.ERROR_PREFIX)


# ---------- 6. свой бот на проход: общий бот цикла матчей не закрываем ----------


@pytest.mark.asyncio
async def test_run_pass_uses_its_own_bot(monkeypatch) -> None:
    seen: dict = {}

    async def fake_send(chat_id, body, buttons, *, detect_gone=False, bot=None):
        seen.update(bot=bot, gone=detect_gone)
        return "ok"

    async def fake_tick(factory, *, now, send):
        return {"ok": 1 if await send(ANNA, "x", []) == "ok" else 0}

    closed: list[int] = []

    async def fake_close():
        closed.append(1)

    monkeypatch.setattr(hn, "send_via_client_bot", fake_send)
    monkeypatch.setattr(hn, "close_client_bot", fake_close)
    monkeypatch.setattr(wn, "run_tick", fake_tick)
    assert await wn.run_pass(now=at(10)) == {"ok": 1}
    assert seen["bot"] is not None and seen["bot"] is not hn._bot and seen["gone"] is True
    assert closed == []
