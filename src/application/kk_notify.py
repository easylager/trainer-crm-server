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
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_notices as hn
from src.application.hockey_game import PICK_CLOSES_BEFORE
from src.application.kk_notify_gate import (
    FAMILY_KK,
    KIND_POLICY,
    Admission,
    GateConfig,
    Recheck,
    admit,
    lock_player,
)
from src.application.kk_notify_journal import UNKNOWN_PHASE, write_journal
from src.application.kk_notify_phase import Phase, PlayerFacts, load_player_facts

logger = logging.getLogger(__name__)


class NoticeStore(Protocol):
    """Где сообщение «занимается» до отправки и где отмечается итог. У игры — ``hockey_notices``, у прогрева
    посетителей (TASK-428) — ``warm_notices``. Семья хранилища должна совпадать с семьёй повода."""

    family: str

    async def claim(self, session: AsyncSession, notice: Any) -> bool: ...

    async def release(self, session: AsyncSession, notice: Any) -> None: ...

    async def mark_done(self, session: AsyncSession, notice: Any, *, ok: bool, now: datetime) -> None: ...

    async def mark_blocked(self, session: AsyncSession, player_key: int, *, now: datetime) -> None: ...


class _HockeyStore:
    family = FAMILY_KK

    async def claim(self, session: AsyncSession, notice: Any) -> bool:
        return await hn.claim(session, notice)

    async def release(self, session: AsyncSession, notice: Any) -> None:
        await hn.release(session, notice)

    async def mark_done(self, session: AsyncSession, notice: Any, *, ok: bool, now: datetime) -> None:
        await hn.mark_done(session, notice, ok=ok, now=now)

    async def mark_blocked(self, session: AsyncSession, player_key: int, *, now: datetime) -> None:
        await hn.mark_blocked(session, player_key, now=now)


HOCKEY_STORE: NoticeStore = _HockeyStore()


@dataclass(frozen=True)
class Proposal:
    """Предложение повода: готовое сообщение и (необязательно) проверка, что оно ещё актуально.
    ``notice`` — ``hn.Notice`` у игры или ``warm_notify.WarmNotice`` у прогрева: ``kind``, ``player_key``,
    ``text``, ``buttons``, ``match_ids``."""

    notice: Any
    recheck: Recheck | None = None
    # Текст на момент отправки (день недели и «сегодня/завтра» считаются тогда, а не при сборке). ``None`` — как в notice.
    render: Callable[[datetime], str] | None = None


# Повод: по состоянию базы и времени предлагает сообщения игрокам. Ничего не отправляет и не пишет.
Producer = Callable[..., Awaitable[list[Proposal]]]
# Сюда срезы 2–4 добавляют поводы; сейчас пусто.
PRODUCERS: dict[str, Producer] = {}  # заполняется ``kk_notify_events.PRODUCERS`` лениво, при первом проходе


# ---------- проверка свежести ----------


def match_still_open(match_id: int, *, min_left: timedelta | None = None) -> Recheck:
    """Матч ещё не начался (с запасом на закрытие хода), всё ещё запланирован и у игрока нет хода на него.
    ``min_left`` — до начала должно остаться не меньше (для «матч сегодня» — 3 часа)."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        row = (
            await session.execute(text("SELECT status, starts_at FROM game_matches WHERE id = :id"), {"id": match_id})
        ).one_or_none()
        if row is None:
            return "no_match"
        if row.status != "scheduled":
            return "match_status"
        if hn._utc(row.starts_at) <= hn._utc(now) + PICK_CLOSES_BEFORE:
            return "match_started"
        if min_left is not None and hn._utc(row.starts_at) < hn._utc(now) + min_left:
            return "too_close"
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
    store: NoticeStore = HOCKEY_STORE,
) -> Outcome:
    """Допуск → занять строку → отправить → отметить → записать в журнал. Единственный путь нового повода к Telegram
    (и игры, и прогрева посетителей: у них разные только хранилища «занято», ``store``).

    Допуск и занятие строки идут в одной транзакции под ``pg_advisory_xact_lock(player_key)``: два цикла (или два
    процесса) не пройдут допуск одновременно по одному игроку, поэтому дневной и недельный лимиты не обходятся гонкой.
    Строка «занято» коммитится до вызова Telegram."""
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
            await lock_player(session, player_key)
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
            if KIND_POLICY[kind].family != store.family:  # повод не той семьи не занимает чужую таблицу
                return await finish(Outcome("skip", "store_mismatch"))
            if proposal.render is not None:
                notice = replace(notice, text=proposal.render(clock()))
            if not await store.claim(session, notice):
                return await finish(Outcome("skip", "already_claimed"))
            await session.commit()  # «занято» видно всем до вызова Telegram; блокировка снята

        try:
            outcome = hn._outcome(await send(player_key, notice.text, notice.buttons))
        except Exception:  # noqa: BLE001 — сбой одного сообщения не роняет остальные
            logger.warning("kk_notify %s/%s send failed", kind, notice.match_ids, exc_info=True)
            outcome = hn.FAILED
        if outcome == hn.GONE:  # чат не найден / аккаунт удалён: недостижим, как после блокировки
            outcome = hn.BLOCKED
        retry_key = (kind, player_key, notice.match_ids)
        if outcome == hn.RETRY and not hn._attempt(retry_key):
            outcome = hn.FAILED
        done_at = clock()
        async with session_factory() as session:
            if outcome == hn.RETRY:
                await store.release(session, notice)
            else:
                hn._RETRIES.pop(retry_key, None)
                await store.mark_done(session, notice, ok=outcome == hn.SENT, now=done_at)
                if outcome == hn.BLOCKED:
                    await store.mark_blocked(session, player_key, now=done_at)
            await session.commit()
        return await finish(Outcome("send", None, outcome))
    except Exception as exc:  # noqa: BLE001 — закрыто по умолчанию: ничего не шлём, причину пишем
        logger.warning("kk_notify dispatch %s/%s failed", kind, player_key, exc_info=True)
        return await finish(Outcome("error", f"{type(exc).__name__}"))


_LAST_PRIORITY = 10**6


def _priority(proposal: Proposal) -> int:
    policy = KIND_POLICY.get(proposal.notice.kind)
    return policy.priority if policy is not None else _LAST_PRIORITY


async def run_tick(
    session_factory,
    *,
    now: datetime,
    send: hn.Sender,
    producers: Mapping[str, Producer] | None = None,
    config: GateConfig | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict[str, int]:
    """Один проход: по каждому игроку выбрать повод и провести его через допуск. Сбой одного игрока, повода или
    всего подготовительного шага не мешает остальным и не пробрасывается в цикл матчей: проход вернёт ``error``."""
    counts: dict[str, int] = {}
    try:
        cfg = config or GateConfig.from_settings()
        if not cfg.enabled:
            return counts
        if producers is None:
            from src.application.kk_notify_events import PRODUCERS as event_producers

            producers = event_producers
        active = [k for k in producers if k in cfg.kinds and k in KIND_POLICY]
        if not active:
            return counts
        try:  # пауза «два приглашения без хода»: сбой не мешает проходу
            from src.application.kk_notify_events import apply_silence_pause

            async with session_factory() as session:
                await apply_silence_pause(session, now=now)
                await session.commit()
        except Exception:  # noqa: BLE001
            logger.warning("kk_notify tick: silence pause failed", exc_info=True)
        async with session_factory() as session:
            facts: dict[int, PlayerFacts] = {f.player_key: f for f in await load_player_facts(session, as_of=now)}
    except Exception:  # noqa: BLE001
        logger.warning("kk_notify tick: setup failed", exc_info=True)
        return {"error": 1}

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
            if proposal.notice.kind != kind:  # повод подсунул сообщение чужого вида: не отправляем
                logger.warning("kk_notify producer %s returned kind %s", kind, proposal.notice.kind)
                counts["kind_mismatch"] = counts.get("kind_mismatch", 0) + 1
                await write_journal(
                    session_factory,
                    tick_at=now,
                    player_key=proposal.notice.player_key,
                    phase=UNKNOWN_PHASE,
                    kind=kind,
                    decision="error",
                    reason="kind_mismatch",
                )
                continue
            by_player.setdefault(proposal.notice.player_key, []).append(proposal)

    for player_key, proposals in sorted(by_player.items()):
        chosen = proposals[0]
        try:
            chosen = min(proposals, key=_priority)
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


__all__ = [
    "HOCKEY_STORE",
    "NoticeStore",
    "Outcome",
    "PRODUCERS",
    "Producer",
    "Proposal",
    "dispatch",
    "match_still_open",
    "run_tick",
    "write_journal",
]
