"""«Кто кого»: путь отправки НОВЫХ поводов и журнал решений (TASK-426, срез 0).

Повод не отправляет сам. Он только предлагает ``Proposal`` (сообщение + проверка свежести), а ``dispatch``
проводит его через единую точку допуска (``kk_notify_gate.admit``), занимает строку в ``hockey_notices`` до вызова
Telegram, отправляет и пишет решение в журнал ``kk_notify_decisions``. Отправителя, минующего ``dispatch``,
для новых поводов нет (тест-трипвайр в ``tests/application/test_kk_notify_guarantees.py``).

Выкатка поэтапная, переменными окружения (см. ``Settings.kk_notify_*``): общий флаг → флаг повода →
сухой прогон (только журнал) → белый список → «тексты приняты» → все.

Срез 0 не содержит ни одного повода и ни одного текста для игроков: ``PRODUCERS`` пуст.

Журнал: одна запись на решение по игроку и проход. Без кандидата записи нет (иначе таблица растёт на
каждого игрока каждые десять минут); повтор одного и того же отказа в течение часа не пишется заново.
Кроме ``player_key`` в журнале нет персональных данных.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_notices as hn
from src.application.hockey_game import PICK_CLOSES_BEFORE
from src.application.kk_notify_gate import (
    KIND_POLICY,
    Admission,
    GateConfig,
    Recheck,
    admit,
)
from src.application.kk_notify_phase import Phase, PlayerFacts, load_player_facts

logger = logging.getLogger(__name__)

JOURNAL_DEDUPE = timedelta(hours=1)
UNKNOWN_PHASE = "unknown"


@dataclass(frozen=True)
class Proposal:
    """Предложение повода: готовое сообщение и (необязательно) проверка, что оно ещё актуально."""

    notice: hn.Notice
    recheck: Recheck | None = None


# Повод: по состоянию базы и времени предлагает сообщения игрокам. Ничего не отправляет и не пишет.
Producer = Callable[..., Awaitable[list[Proposal]]]
# Сюда срезы 2–4 добавляют поводы; сейчас пусто.
PRODUCERS: dict[str, Producer] = {}


# ---------- журнал ----------

_JOURNAL_RECENT = text("""
    SELECT 1 FROM kk_notify_decisions
    WHERE player_key = :player_key AND kind IS NOT DISTINCT FROM :kind AND decision = :decision
      AND reason IS NOT DISTINCT FROM :reason AND tick_at >= :since
    LIMIT 1
    """)

_JOURNAL_INSERT = text("""
    INSERT INTO kk_notify_decisions (tick_at, player_key, phase, kind, decision, reason, result)
    VALUES (:tick_at, :player_key, :phase, :kind, :decision, :reason, :result)
    """)


async def write_journal(
    session_factory,
    *,
    tick_at: datetime,
    player_key: int,
    phase: str,
    kind: str | None,
    decision: str,
    reason: str | None = None,
    result: str | None = None,
) -> None:
    """Записать решение. Сбой журнала не должен ни остановить рассылку, ни отправить лишнего — только лог."""
    try:
        params = {
            "tick_at": tick_at,
            "player_key": player_key,
            "phase": phase,
            "kind": kind,
            "decision": decision,
            "reason": reason,
            "result": result,
        }
        async with session_factory() as session:
            if decision != "send":
                recent = await session.execute(_JOURNAL_RECENT, {**params, "since": tick_at - JOURNAL_DEDUPE})
                if recent.first() is not None:
                    return
            await session.execute(_JOURNAL_INSERT, params)
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.warning("kk_notify journal write failed for %s", player_key, exc_info=True)


# ---------- проверка свежести ----------


def match_still_open(match_id: int) -> Recheck:
    """Матч ещё не начался (с запасом на закрытие хода), всё ещё запланирован и у игрока нет хода на него."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        row = (
            await session.execute(
                text("SELECT status, starts_at FROM game_matches WHERE id = :id"), {"id": match_id}
            )
        ).one_or_none()
        if row is None:
            return "no_match"
        if row.status != "scheduled":
            return "match_status"
        if hn._utc(row.starts_at) <= hn._utc(now) + PICK_CLOSES_BEFORE:
            return "match_started"
        has_pick = (
            await session.execute(
                text("SELECT 1 FROM hockey_picks WHERE match_id = :m AND player_key = :p"),
                {"m": match_id, "p": player_key},
            )
        ).first()
        if has_pick:
            return "has_pick"
        return None

    return check


# ---------- отправка ----------


@dataclass(frozen=True)
class Outcome:
    decision: str  # send | skip | dry_run | error
    reason: str | None = None
    result: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def dispatch(
    session_factory,
    proposal: Proposal,
    *,
    phase: str,
    tick_at: datetime,
    send: hn.Sender,
    config: GateConfig,
    clock: Callable[[], datetime] = _now,
) -> Outcome:
    """Допуск → занять строку → отправить → отметить → записать в журнал. Единственный путь нового повода к Telegram."""
    notice = proposal.notice
    kind, player_key = notice.kind, notice.player_key

    async def finish(outcome: Outcome) -> Outcome:
        await write_journal(
            session_factory,
            tick_at=tick_at,
            player_key=player_key,
            phase=phase,
            kind=kind,
            decision=outcome.decision,
            reason=outcome.reason,
            result=outcome.result,
        )
        return outcome

    try:
        async with session_factory() as session:
            admission: Admission = await admit(
                session,
                kind=kind,
                player_key=player_key,
                now=clock(),
                config=config,
                recheck=proposal.recheck,
            )
        if not admission.allowed:
            return await finish(Outcome("dry_run" if admission.dry_run else "skip", admission.reason))
        if kind not in KIND_POLICY or not KIND_POLICY[kind].new:
            return await finish(Outcome("skip", "not_a_new_kind"))

        async with session_factory() as session:
            if not await hn.claim(session, notice):
                return await finish(Outcome("skip", "already_claimed"))
            await session.commit()

        try:
            outcome = hn._outcome(await send(player_key, notice.text, notice.buttons))
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("kk_notify %s/%s send failed", kind, notice.match_id, exc_info=True)
            outcome = hn.FAILED
        retry_key = (kind, player_key, notice.match_ids)
        if outcome == hn.RETRY and not hn._attempt(retry_key):
            outcome = hn.FAILED
        done_at = clock()
        async with session_factory() as session:
            if outcome == hn.RETRY:
                await hn.release(session, notice)
            else:
                hn._RETRIES.pop(retry_key, None)
                await hn.mark_done(session, notice, ok=outcome == hn.SENT, now=done_at)
                if outcome == hn.BLOCKED:
                    await hn.mark_blocked(session, player_key, now=done_at)
            await session.commit()
        return await finish(Outcome("send", None, outcome))
    except Exception as exc:  # noqa: BLE001 — закрыто по умолчанию: ничего не шлём, причину пишем
        logger.warning("kk_notify dispatch %s/%s failed", kind, player_key, exc_info=True)
        return await finish(Outcome("error", f"{type(exc).__name__}"))


async def run_tick(
    session_factory,
    *,
    now: datetime,
    send: hn.Sender,
    producers: Mapping[str, Producer] | None = None,
    config: GateConfig | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict[str, int]:
    """Один проход: по каждому игроку выбрать повод и провести его через допуск. Сбой одного игрока не мешает остальным."""
    cfg = config or GateConfig.from_settings()
    counts: dict[str, int] = {}
    if not cfg.enabled:
        return counts
    producers = PRODUCERS if producers is None else producers
    active = [k for k in producers if k in cfg.kinds and k in KIND_POLICY]
    if not active:
        return counts

    async with session_factory() as session:
        facts: dict[int, PlayerFacts] = {f.player_key: f for f in await load_player_facts(session, as_of=now)}

    by_player: dict[int, list[Proposal]] = {}
    for kind in active:
        try:
            async with session_factory() as session:
                proposals = await producers[kind](session, now=now)
        except Exception:  # noqa: BLE001 — упавший повод не мешает остальным
            logger.warning("kk_notify producer %s failed", kind, exc_info=True)
            counts["producer_errors"] = counts.get("producer_errors", 0) + 1
            continue
        for proposal in proposals:
            by_player.setdefault(proposal.notice.player_key, []).append(proposal)

    for player_key, proposals in sorted(by_player.items()):
        chosen = min(proposals, key=lambda p: KIND_POLICY[p.notice.kind].priority)
        try:
            player = facts.get(player_key)
            phase = player.phase(now).value if player is not None else Phase.OFF.value
            if player is None:
                outcome = Outcome("skip", "unknown_player")
                await write_journal(
                    session_factory,
                    tick_at=now,
                    player_key=player_key,
                    phase=phase,
                    kind=chosen.notice.kind,
                    decision=outcome.decision,
                    reason=outcome.reason,
                )
            else:
                outcome = await dispatch(
                    session_factory, chosen, phase=phase, tick_at=now, send=send, config=cfg, clock=clock
                )
        except Exception:  # noqa: BLE001
            logger.warning("kk_notify tick: player %s failed", player_key, exc_info=True)
            await write_journal(
                session_factory,
                tick_at=now,
                player_key=player_key,
                phase=UNKNOWN_PHASE,
                kind=chosen.notice.kind,
                decision="error",
                reason="tick",
            )
            outcome = Outcome("error", "tick")
        key = outcome.result if outcome.decision == "send" else outcome.decision
        counts[key or "skip"] = counts.get(key or "skip", 0) + 1
    return counts


__all__ = ["Outcome", "PRODUCERS", "Producer", "Proposal", "dispatch", "match_still_open", "run_tick", "write_journal"]
