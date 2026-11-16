"""TASK-426 B9: гарантии 1–12 для новых поводов (invite, comeback, week, month, consent) — через настоящие виды."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from kk_notify_helpers import SASHA, Outbox, at, make_factory, seed_match, seed_notice, seed_player
from sqlalchemy import text

from src.application import hockey_notices as hn
from src.application import kk_notify_gate as gate
from src.application import kk_notify_report as report
from src.application.kk_notify import Proposal, dispatch
from src.application.kk_notify_gate import GateConfig, admit

KINDS = ["invite", "comeback", "week", "month", "consent"]
NEEDS_CONSENT = [k for k in KINDS if k != "consent"]
ALL = frozenset(KINDS)
CFG = GateConfig(enabled=True, dry_run=False, texts_accepted=True, kinds=ALL)
NOW = at(12)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _env(monkeypatch) -> None:
    monkeypatch.setenv("CLIENT_BOT_USERNAME", "glide_test_bot")
    hn._RETRIES.clear()


@pytest.fixture
def factory(db_session):
    return make_factory(db_session)


async def _p(db, kind, key=SASHA, recheck=None) -> Proposal:
    mid = await seed_match(db, at(19, day=12))
    return Proposal(hn.Notice(kind, key, mid, "тест", []), recheck)


async def _go(factory, p, *, send, now=NOW, config=CFG):
    return await dispatch(factory, p, phase="active", tick_at=now, send=send, config=config, clock=lambda: now)


async def _player(db, **prefs):
    prefs.setdefault("notify_consent", True)
    await seed_player(db, SASHA, registered=at(10, day=1), **prefs)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_happy_path_sends_once_and_journals(db_session, factory, kind) -> None:
    await _player(db_session)
    p, out = await _p(db_session, kind), Outbox()
    first = await _go(factory, p, send=out)
    second = await _go(factory, p, send=out)  # дубль: тот же повод повторно
    assert (first.decision, first.result) == ("send", "ok") and second.decision == "skip" and len(out.sent) == 1
    rows = (await db_session.execute(text("SELECT kind, decision FROM kk_notify_decisions ORDER BY id"))).all()
    assert [tuple(r) for r in rows][0] == (kind, "send")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("config", "prefs", "now", "reason"),
    [
        (GateConfig(kinds=ALL), {}, NOW, gate.DISABLED),
        (GateConfig(enabled=True, dry_run=False, texts_accepted=True), {}, NOW, gate.KIND_OFF),
        (GateConfig(enabled=True, dry_run=False, texts_accepted=False, kinds=ALL), {}, NOW, gate.TEXTS_NOT_ACCEPTED),
        (CFG, {}, at(23, 0), gate.QUIET),
        (CFG, {}, at(8, 59), gate.QUIET),
        (CFG, {"remind": False}, NOW, gate.OPTED_OUT),
        (CFG, {"blocked_at": at(1, day=9)}, NOW, gate.BLOCKED),
        (CFG, {"paused_until": at(12, day=20)}, NOW, gate.PAUSED),
    ],
)
async def test_refusals_send_nothing(db_session, factory, kind, config, prefs, now, reason) -> None:
    await _player(db_session, **prefs)
    out = Outbox()
    result = await _go(factory, await _p(db_session, kind), send=out, now=now, config=config)
    assert out.sent == [] and result.reason == reason


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", NEEDS_CONSENT)
@pytest.mark.parametrize("consent", [None, False])
async def test_no_consent_no_message(db_session, factory, kind, consent) -> None:
    (
        await _player(db_session, notify_consent=consent)
        if consent is not None
        else await seed_player(db_session, SASHA, registered=at(10, day=1))
    )
    out = Outbox()
    assert (await _go(factory, await _p(db_session, kind), send=out)).reason == gate.NO_CONSENT and out.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_whitelist_lets_trial_player_through_without_accepted_texts(db_session, factory, kind) -> None:
    await _player(db_session)
    cfg = GateConfig(enabled=True, dry_run=False, texts_accepted=False, kinds=ALL, whitelist=frozenset({SASHA}))
    out = Outbox()
    await _go(factory, await _p(db_session, kind), send=out, config=cfg)
    assert len(out.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_dry_run_only_journals(db_session, factory, kind) -> None:
    await _player(db_session)
    cfg = GateConfig(enabled=True, dry_run=True, texts_accepted=True, kinds=ALL)
    out = Outbox()
    result = await _go(factory, await _p(db_session, kind), send=out, config=cfg)
    assert out.sent == [] and result.decision == "dry_run"
    assert (await db_session.execute(text("SELECT 1 FROM hockey_notices WHERE kind = :k"), {"k": kind})).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_daily_and_weekly_caps(db_session, factory, kind) -> None:
    await _player(db_session)
    await seed_notice(db_session, SASHA, "nomove", at(10, 0))
    assert (await admit(db_session, kind=kind, player_key=SASHA, now=NOW, config=CFG)).reason == gate.DAILY_LIMIT
    await db_session.execute(text("DELETE FROM hockey_notices"))
    for days in (5, 3, 1):
        await seed_notice(db_session, SASHA, "result" if False else "mfinal", at(12, day=10 - days))
    assert (await admit(db_session, kind=kind, player_key=SASHA, now=NOW, config=CFG)).reason == gate.WEEKLY_LIMIT


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_stale_recheck_blocks_send(db_session, factory, kind) -> None:
    await _player(db_session)

    async def stale(session, player_key, now):
        return "match_started"

    out = Outbox()
    result = await _go(factory, await _p(db_session, kind, recheck=stale), send=out)
    assert out.sent == [] and result.reason == "stale:match_started"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_gone_and_blocked_switch_player_off_and_stop(db_session, factory, kind) -> None:
    await _player(db_session)
    out = Outbox(answer=hn.GONE)
    assert (await _go(factory, await _p(db_session, kind), send=out)).result == hn.BLOCKED
    again = await _go(factory, await _p(db_session, kind), send=out, now=at(15))
    assert again.reason == gate.BLOCKED and len(out.sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_temporary_failures_are_capped(db_session, factory, kind) -> None:
    await _player(db_session)
    p, out = await _p(db_session, kind), Outbox(answer=hn.RETRY)
    for _ in range(hn.MAX_ATTEMPTS + 3):
        await _go(factory, p, send=out)
    assert len(out.sent) == hn.MAX_ATTEMPTS


def test_producers_cannot_send_by_themselves() -> None:
    src = (ROOT / "src/application/kk_notify_events.py").read_text(encoding="utf-8")
    for forbidden in ("send_via_client_bot", "send_message", "hn.claim(", "mark_done(", ".send("):
        assert forbidden not in src, forbidden


def test_every_new_kind_fits_the_database_and_is_registered() -> None:
    migration = (ROOT / "migrations/versions/0328_kk_notify_kinds.py").read_text(encoding="utf-8")
    for kind in KINDS:
        assert f'"{kind}"' in migration and kind in gate.KIND_POLICY and len(kind) <= 12


@pytest.mark.asyncio
async def test_report_lists_new_kinds_and_conversion(db_session) -> None:
    await _player(db_session)
    sent = at(14, day=12)
    await seed_notice(db_session, SASHA, "invite", sent)
    await seed_notice(db_session, SASHA, "week", sent + timedelta(hours=1))
    await seed_notice(db_session, SASHA, "consent", None, failed=True, created_at=sent)
    from kk_notify_helpers import seed_pick

    await seed_pick(db_session, SASHA, sent + timedelta(hours=3))
    got = await report.collect(db_session, now=at(10, day=16))
    assert got.sent == {"invite": 1, "week": 1} and got.failed == {"consent": 1}
    assert got.invites["invite"] == (1, 1)
    body = report.render_report(got, report.Thresholds())
    assert "«матч сегодня или завтра» 1" in body and "итогов недели 1" in body
    assert "— «матч сегодня или завтра»: 1 из 1 (100 %)" in body and "— возврат: не было сообщений" in body
