"""Прогрев разовых посетителей катков (TASK-428): серия подписчикам и одно напоминание «знающим нас».

Поводы только предлагают сообщения (``Proposal``). Отправляет их тот же ``kk_notify.dispatch``, что и игру: единая
точка допуска ``kk_notify_gate`` (тихие часы 23:00–09:00 по Минску, 1 в сутки и 3 в неделю — общие с игрой и
колокольчиком катка, «Не присылать», блокировка, флаги ``WARM_*``, сухой прогон), замок на человека, «занято»
строкой ``warm_notices`` до вызова Telegram, журнал решений ``kk_notify_decisions``. Своих правил допуска здесь нет.

Поводы:

* ``warm_welcome`` — после подписки на каток (``client_ice_watches``, ``sessions``), один раз на человека: что будем
  присылать и ближайшие 1–2 сеанса. Окно — двое суток после подписки (ночью ждёт утра, лимит дня — следующего дня).
* ``warm_today`` — утром 09:00–11:00 в день, когда на подписанном катке есть сеанс; раз в сутки.
* ``warm_week`` — по четвергам 09:00–11:00 подборка сеансов катка на неделю; раз в неделю, если есть что показать.
* ``warm_nudge`` — одно напоминание за всё время тому, кто запускал бота (``clients.telegram_id``), был в каталоге
  Mini App ровно один день 3–7 суток назад и ни на что не подписан. Совпадение ``actor_hash`` с Telegram считается
  в памяти (``telegram_actor_hash``) и нигде не хранится. Без ответа — больше не пишем никогда.

Серия B идёт только по явной подписке: повод перепроверяет её прямо перед отправкой (``recheck``). Любое
«Не присылать» (``warm:off``) выключает все поводы прогрева сразу. Подписка на изменения расписания (колокольчик)
от него не меняется: у неё своя кнопка «Отменить рассылку».
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_notices as hn
from src.application import warm_texts as wt
from src.application.client_ice_watch_filters import session_matches_filter
from src.application.kk_notify import Outcome, Producer, Proposal, dispatch
from src.application.kk_notify_gate import (
    FAMILY_WARM,
    KIND_POLICY,
    KIND_WARM_NUDGE,
    KIND_WARM_TODAY,
    KIND_WARM_WEEK,
    KIND_WARM_WELCOME,
    GateConfig,
    Recheck,
)
from src.application.kk_notify_journal import UNKNOWN_PHASE, write_journal
from src.shared.copy_ru import t

logger = logging.getLogger(__name__)

PHASE_SUBSCRIBER = "subscriber"  # серия B: есть подписка на каток
PHASE_KNOWN = "known"  # напоминание C: запускал бота, смотрел каталог, не подписан

MORNING_FROM, MORNING_TO = 9, 11  # окно утренних поводов по Минску: [9:00, 11:00)
WEEK_WEEKDAY = 3  # четверг: подборка перед выходными
WELCOME_WINDOW = timedelta(hours=48)
# Сеанс «сегодня» предлагаем, если до него не меньше часа (дорога до катка); перед отправкой — не меньше 30 минут.
TODAY_MIN_LEFT = timedelta(hours=1)
TODAY_RECHECK_MIN_LEFT = timedelta(minutes=30)
WEEK_HORIZON = timedelta(days=7)
NUDGE_MIN_DAYS, NUDGE_MAX_DAYS = 3, 7

CB_OFF = "warm:off"
CB_ON = "warm:on"
CB_SUB = "warm:sub"  # warm:sub:<arena_id>

REF_ONCE = "once"
_PUBLIC_KINDS = ("public_skate", "open_ice")


def _utc(value: datetime) -> datetime:
    return hn._utc(value)


def _local(value: datetime) -> datetime:
    return _utc(value).astimezone(wt.MINSK_TZ)


def in_morning(now: datetime) -> bool:
    hour = _local(now).hour
    return MORNING_FROM <= hour < MORNING_TO


def day_ref(now: datetime) -> str:
    return f"d{_local(now).date().isoformat()}"


def week_ref(now: datetime) -> str:
    iso = _local(now).isocalendar()
    return f"w{iso.year}-W{iso.week:02d}"


# ---------- сообщение и хранилище «занято» ----------


@dataclass(frozen=True)
class WarmNotice:
    kind: str
    player_key: int  # telegram_id: тот же ключ человека, что у игры
    ref: str
    text: str
    buttons: list[list[dict]] = field(default_factory=list)
    arena_id: int | None = None

    @property
    def match_ids(self) -> tuple[str, ...]:  # ключ повторов в ``dispatch``
        return (self.ref,)


_CLAIM = text("""
    INSERT INTO warm_notices (telegram_id, kind, ref, arena_id) VALUES (:k, :kind, :ref, :arena)
    ON CONFLICT DO NOTHING RETURNING telegram_id
    """)
_RELEASE = text("""
    DELETE FROM warm_notices WHERE telegram_id = :k AND kind = :kind AND ref = :ref AND sent_at IS NULL AND NOT failed
    """)
_DONE = text("""
    UPDATE warm_notices
    SET sent_at = CASE WHEN CAST(:ok AS BOOLEAN) THEN CAST(:now AS TIMESTAMPTZ) END, failed = NOT CAST(:ok AS BOOLEAN)
    WHERE telegram_id = :k AND kind = :kind AND ref = :ref
    """)
_MARK_BLOCKED = text("""
    INSERT INTO warm_prefs (telegram_id, bot_blocked_at) VALUES (:k, :now)
    ON CONFLICT (telegram_id) DO UPDATE SET bot_blocked_at = EXCLUDED.bot_blocked_at, updated_at = now()
    """)


def _key(notice: WarmNotice) -> dict[str, Any]:
    return {"k": notice.player_key, "kind": notice.kind, "ref": notice.ref}


class _WarmStore:
    family = FAMILY_WARM

    async def claim(self, session: AsyncSession, notice: WarmNotice) -> bool:
        row = (await session.execute(_CLAIM, {**_key(notice), "arena": notice.arena_id})).first()
        return row is not None

    async def release(self, session: AsyncSession, notice: WarmNotice) -> None:
        await session.execute(_RELEASE, _key(notice))

    async def mark_done(self, session: AsyncSession, notice: WarmNotice, *, ok: bool, now: datetime) -> None:
        await session.execute(_DONE, {**_key(notice), "ok": ok, "now": _utc(now)})

    async def mark_blocked(self, session: AsyncSession, player_key: int, *, now: datetime) -> None:
        await session.execute(_MARK_BLOCKED, {"k": player_key, "now": _utc(now)})


WARM_STORE = _WarmStore()


# ---------- «Не присылать» ----------

_SET_OPT_OUT = text("""
    INSERT INTO warm_prefs (telegram_id, opted_out_at) VALUES (:k, :at)
    ON CONFLICT (telegram_id) DO UPDATE SET opted_out_at = EXCLUDED.opted_out_at, updated_at = now()
    """)
_CLEAR_BLOCKED = text(
    "UPDATE warm_prefs SET bot_blocked_at = NULL, updated_at = now() WHERE telegram_id = :k AND bot_blocked_at IS NOT NULL"
)


async def set_opt_out(session: AsyncSession, telegram_id: int, off: bool, *, now: datetime | None = None) -> None:
    """«Не присылать» (``off=True``) выключает все поводы прогрева сразу; «Присылать» возвращает."""
    at = _utc(now or datetime.now(timezone.utc)) if off else None
    await session.execute(_SET_OPT_OUT, {"k": int(telegram_id), "at": at})


async def clear_blocked(session: AsyncSession, telegram_id: int) -> None:
    """Человек снова сам что-то сделал в боте (подписался): блокировка, замеченная прогревом, снята."""
    await session.execute(_CLEAR_BLOCKED, {"k": int(telegram_id)})


def off_button() -> dict:
    return {"text": t("warm.btn.off"), "callback_data": CB_OFF}


def on_button() -> dict:
    return {"text": t("warm.btn.on"), "callback_data": CB_ON}


def subscribe_callback(arena_id: int) -> str:
    return f"{CB_SUB}:{int(arena_id)}"


def parse_subscribe_callback(data: str | None) -> int | None:
    raw = data or ""
    prefix = f"{CB_SUB}:"
    if not raw.startswith(prefix):
        return None
    tail = raw[len(prefix) :]
    return int(tail) if tail.isdigit() and 0 < int(tail) < 2**31 else None


def _schedule_buttons(arena_id: int) -> list[list[dict]]:
    return hn._rows([hn.url_button(t("warm.btn.schedule"), f"arena_{int(arena_id)}")], [off_button()])


def _nudge_buttons(arena_id: int) -> list[list[dict]]:
    return [[{"text": t("warm.btn.subscribe"), "callback_data": subscribe_callback(arena_id)}], [off_button()]]


# ---------- общие запросы ----------

_WATCHES = text("""
    SELECT w.id, w.telegram_id, w.arena_id, w.filter_json, w.created_at,
           COALESCE(NULLIF(TRIM(a.name), ''), 'Каток') AS arena_name
    FROM client_ice_watches AS w
    JOIN arenas AS a ON a.id = w.arena_id
    WHERE w.active AND w.watch_kind = 'sessions' AND w.telegram_id > 0
      AND (CAST(:since AS TIMESTAMPTZ) IS NULL OR w.created_at >= :since)
    ORDER BY w.telegram_id, w.created_at, w.id
    """)

_SESSIONS = text("""
    SELECT id, arena_id, starts_at_utc FROM ice_sessions
    WHERE arena_id = ANY(:arenas) AND status = 'active' AND kind = ANY(:kinds)
      AND starts_at_utc >= :from_ AND starts_at_utc < :until
    ORDER BY starts_at_utc, id
    """)

_WATCH_ACTIVE = text("SELECT 1 FROM client_ice_watches WHERE id = :id AND active AND telegram_id = :k")

_DONE_KIND = text("SELECT 1 FROM warm_notices WHERE telegram_id = :k AND kind = :kind AND ref = :ref")


async def _watches(session: AsyncSession, *, since: datetime | None = None) -> list[dict]:
    rows = (await session.execute(_WATCHES, {"since": _utc(since) if since else None})).mappings().all()
    return [dict(r) for r in rows]


async def _sessions(
    session: AsyncSession, arenas: list[int], *, from_: datetime, until: datetime
) -> dict[int, list[dict]]:
    if not arenas:
        return {}
    out: dict[int, list[dict]] = {}
    params = {"arenas": arenas, "kinds": list(_PUBLIC_KINDS), "from_": _utc(from_), "until": _utc(until)}
    for r in (await session.execute(_SESSIONS, params)).mappings().all():
        out.setdefault(int(r["arena_id"]), []).append(dict(r))
    return out


def _matching(sessions: list[dict], watch: Mapping[str, Any], now: datetime) -> list[dict]:
    return [s for s in sessions if session_matches_filter(s, watch.get("filter_json"), now=now)]


def _all_of(*checks: Recheck) -> Recheck:
    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        for one in checks:
            reason = await one(session, player_key, now)
            if reason:
                return reason
        return None

    return check


def watch_still_active(watch_id: int) -> Recheck:
    """Согласие серии B — явная подписка: перед отправкой она всё ещё включена."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        row = (await session.execute(_WATCH_ACTIVE, {"id": int(watch_id), "k": int(player_key)})).first()
        return None if row is not None else "no_subscription"

    return check


async def _morning_check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
    return None if in_morning(now) else "out_of_window"


def _within(until: datetime) -> Recheck:
    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        return None if _utc(now) < _utc(until) else "out_of_window"

    return check


def sessions_still_ahead(session_ids: list[int], *, min_left: timedelta) -> Recheck:
    """Хоть один из сеансов сообщения всё ещё в силе и начнётся не раньше чем через ``min_left``."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        row = (
            await session.execute(
                text("""
                    SELECT 1 FROM ice_sessions
                    WHERE id = ANY(:ids) AND status = 'active' AND starts_at_utc >= :from_ LIMIT 1
                    """),
                {"ids": [int(i) for i in session_ids], "from_": _utc(now) + min_left},
            )
        ).first()
        return None if row is not None else "no_sessions"

    return check


def _starts(rows: list[dict]) -> list[datetime]:
    return [_utc(r["starts_at_utc"]) for r in rows]


# ---------- B1. после подписки ----------


async def produce_welcome(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    out: list[Proposal] = []
    seen: set[int] = set()
    watches = await _watches(session, since=now - WELCOME_WINDOW)
    future = await _sessions(
        session, sorted({int(w["arena_id"]) for w in watches}), from_=now, until=now + timedelta(days=14)
    )
    for w in watches:
        tid = int(w["telegram_id"])
        if tid in seen:  # одно приветствие на человека: первая подписка в окне
            continue
        seen.add(tid)
        if (await session.execute(_DONE_KIND, {"k": tid, "kind": KIND_WARM_WELCOME, "ref": REF_ONCE})).first():
            continue
        arena_id = int(w["arena_id"])
        starts = _starts(_matching(future.get(arena_id, []), w, now))
        name = str(w["arena_name"])

        def render(sent_now: datetime, name=name, starts=starts) -> str:
            return wt.welcome_text(arena_name=name, starts=starts, now=sent_now)

        notice = WarmNotice(KIND_WARM_WELCOME, tid, REF_ONCE, render(now), _schedule_buttons(arena_id), arena_id)
        recheck = _all_of(watch_still_active(int(w["id"])), _within(_utc(w["created_at"]) + WELCOME_WINDOW))
        out.append(Proposal(notice, recheck, render))
    return out


# ---------- B2. утром в день сеанса ----------


async def produce_today(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not in_morning(now):
        return []
    watches = await _watches(session)
    day_end = _local(now).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    today = await _sessions(
        session, sorted({int(w["arena_id"]) for w in watches}), from_=now + TODAY_MIN_LEFT, until=day_end
    )
    best: dict[int, tuple[datetime, dict, list[dict]]] = {}
    for w in watches:
        rows = _matching(today.get(int(w["arena_id"]), []), w, now)
        if not rows:
            continue
        tid = int(w["telegram_id"])
        first = _utc(rows[0]["starts_at_utc"])
        if tid not in best or first < best[tid][0]:  # несколько катков — тот, где лёд раньше
            best[tid] = (first, w, rows)
    ref = day_ref(now)
    out: list[Proposal] = []
    for tid, (_, w, rows) in sorted(best.items()):
        if (await session.execute(_DONE_KIND, {"k": tid, "kind": KIND_WARM_TODAY, "ref": ref})).first():
            continue
        arena_id, name, starts = int(w["arena_id"]), str(w["arena_name"]), _starts(rows)
        body = wt.today_text(arena_name=name, starts=starts, now=now)
        if body is None:
            continue

        def render(sent_now: datetime, name=name, starts=starts, body=body) -> str:
            return wt.today_text(arena_name=name, starts=starts, now=sent_now) or body

        notice = WarmNotice(KIND_WARM_TODAY, tid, ref, body, _schedule_buttons(arena_id), arena_id)
        recheck = _all_of(
            _morning_check,
            watch_still_active(int(w["id"])),
            sessions_still_ahead([int(r["id"]) for r in rows], min_left=TODAY_RECHECK_MIN_LEFT),
        )
        out.append(Proposal(notice, recheck, render))
    return out


# ---------- B3. неделя ----------


async def produce_week(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not in_morning(now) or _local(now).weekday() != WEEK_WEEKDAY:
        return []
    watches = await _watches(session)
    ahead = await _sessions(
        session, sorted({int(w["arena_id"]) for w in watches}), from_=now + TODAY_MIN_LEFT, until=now + WEEK_HORIZON
    )
    best: dict[int, tuple[int, dict, list[dict]]] = {}
    for w in watches:
        rows = _matching(ahead.get(int(w["arena_id"]), []), w, now)
        if not rows:
            continue
        tid = int(w["telegram_id"])
        if tid not in best or len(rows) > best[tid][0]:  # несколько катков — тот, где сеансов больше
            best[tid] = (len(rows), w, rows)
    ref = week_ref(now)
    out: list[Proposal] = []
    for tid, (_, w, rows) in sorted(best.items()):
        if (await session.execute(_DONE_KIND, {"k": tid, "kind": KIND_WARM_WEEK, "ref": ref})).first():
            continue
        arena_id, name, starts = int(w["arena_id"]), str(w["arena_name"]), _starts(rows)
        body = wt.week_text(arena_name=name, starts=starts, now=now)
        if body is None:
            continue

        def render(sent_now: datetime, name=name, starts=starts, body=body) -> str:
            return wt.week_text(arena_name=name, starts=starts, now=sent_now) or body

        notice = WarmNotice(KIND_WARM_WEEK, tid, ref, body, _schedule_buttons(arena_id), arena_id)
        recheck = _all_of(
            _morning_check,
            watch_still_active(int(w["id"])),
            sessions_still_ahead([int(r["id"]) for r in rows], min_left=TODAY_RECHECK_MIN_LEFT),
        )
        out.append(Proposal(notice, recheck, render))
    return out


# ---------- C. одно напоминание «знающим нас» ----------

# Достижимые: запускали бота, не заблокировали, не нажимали «Не присылать», ни на что не подписаны, напоминания
# не получали. Служебные аккаунты каталога в событиях не пишутся, поэтому и сюда не попадут.
_KNOWN = text("""
    SELECT DISTINCT c.telegram_id FROM clients AS c
    WHERE c.telegram_id > 0 AND NOT COALESCE(c.is_sandbox, false)
      AND NOT EXISTS (SELECT 1 FROM client_ice_watches AS w WHERE w.telegram_id = c.telegram_id AND w.active)
      AND NOT EXISTS (SELECT 1 FROM warm_notices AS n WHERE n.telegram_id = c.telegram_id AND n.kind = 'warm_nudge')
      AND NOT EXISTS (SELECT 1 FROM warm_prefs AS p WHERE p.telegram_id = c.telegram_id
                      AND (p.opted_out_at IS NOT NULL OR p.bot_blocked_at IS NOT NULL))
      AND NOT EXISTS (SELECT 1 FROM hockey_player_prefs AS hp WHERE hp.player_key = c.telegram_id
                      AND hp.bot_blocked_at IS NOT NULL)
    """)

# Визиты в Mini App каталога по актёру: дни по Минску и самый частый каток.
_VISITS = text("""
    SELECT actor_hash,
           COUNT(DISTINCT (occurred_at AT TIME ZONE 'Europe/Minsk')::date) AS days,
           MIN((occurred_at AT TIME ZONE 'Europe/Minsk')::date) AS first_day,
           MODE() WITHIN GROUP (ORDER BY arena_id) FILTER (WHERE arena_id IS NOT NULL) AS arena_id
    FROM catalog_consumer_events
    WHERE kind = 'miniapp_catalog_entry' AND actor_hash = ANY(:hashes)
    GROUP BY actor_hash
    """)

_ARENA = text("""
    SELECT COALESCE(NULLIF(TRIM(a.name), ''), 'Каток') AS name FROM arenas AS a WHERE a.id = :id AND a.is_active
    """)


def _hash_map(telegram_ids: list[int]) -> dict[str, int]:
    """``actor_hash`` → ``telegram_id`` — только в памяти этого прохода. Без секрета актёра пусто (закрыто)."""
    from src.application.catalog_consumer_events import telegram_actor_hash

    out: dict[str, int] = {}
    for tid in telegram_ids:
        actor = telegram_actor_hash(tid)
        if actor:
            out[actor] = tid
    return out


@dataclass(frozen=True)
class KnownVisitor:
    telegram_id: int
    visit_day: date
    arena_id: int | None


async def single_visit_known(session: AsyncSession, *, telegram_ids: list[int]) -> list[KnownVisitor]:
    """Кто из этих людей был в каталоге Mini App ровно один день (по Минску), и какой каток там смотрел."""
    by_hash = _hash_map(telegram_ids)
    if not by_hash:
        return []
    rows = (await session.execute(_VISITS, {"hashes": list(by_hash)})).mappings().all()
    out = []
    for r in rows:
        if int(r["days"]) != 1 or r["actor_hash"] not in by_hash:
            continue
        arena = r["arena_id"]
        out.append(KnownVisitor(by_hash[r["actor_hash"]], r["first_day"], int(arena) if arena is not None else None))
    return out


def nudge_due(visit_day: date, now: datetime) -> bool:
    days = (_local(now).date() - visit_day).days
    return NUDGE_MIN_DAYS <= days <= NUDGE_MAX_DAYS


def still_single_visit(visit_day: date) -> Recheck:
    """Перед отправкой: человек так и не вернулся и не подписался (вернулся — уже не разовый, не пишем)."""

    async def check(session: AsyncSession, player_key: int, now: datetime) -> str | None:
        subscribed = (
            await session.execute(
                text("SELECT 1 FROM client_ice_watches WHERE telegram_id = :k AND active LIMIT 1"), {"k": player_key}
            )
        ).first()
        if subscribed is not None:
            return "subscribed"
        visits = await single_visit_known(session, telegram_ids=[player_key])
        if len(visits) != 1 or visits[0].visit_day != visit_day:
            return "visited_again"
        return None

    return check


async def produce_nudge(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not in_morning(now):
        return []
    tids = [int(r[0]) for r in (await session.execute(_KNOWN)).all()]
    out: list[Proposal] = []
    for visitor in await single_visit_known(session, telegram_ids=tids):
        if visitor.arena_id is None or not nudge_due(visitor.visit_day, now):
            continue  # без катка подписываться не на что
        arena = (await session.execute(_ARENA, {"id": visitor.arena_id})).first()
        if arena is None:
            continue
        notice = WarmNotice(
            KIND_WARM_NUDGE,
            visitor.telegram_id,
            REF_ONCE,
            wt.nudge_text(arena_name=str(arena.name)),
            _nudge_buttons(visitor.arena_id),
            visitor.arena_id,
        )
        out.append(Proposal(notice, _all_of(_morning_check, still_single_visit(visitor.visit_day))))
    return out


PRODUCERS: dict[str, Producer] = {
    KIND_WARM_WELCOME: produce_welcome,
    KIND_WARM_TODAY: produce_today,
    KIND_WARM_WEEK: produce_week,
    KIND_WARM_NUDGE: produce_nudge,
}
PHASES = {
    KIND_WARM_WELCOME: PHASE_SUBSCRIBER,
    KIND_WARM_TODAY: PHASE_SUBSCRIBER,
    KIND_WARM_WEEK: PHASE_SUBSCRIBER,
    KIND_WARM_NUDGE: PHASE_KNOWN,
}


# ---------- проход ----------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _priority(proposal: Proposal) -> int:
    policy = KIND_POLICY.get(proposal.notice.kind)
    return policy.priority if policy is not None else 10**6


async def run_tick(
    session_factory,
    *,
    now: datetime,
    send: hn.Sender,
    producers: Mapping[str, Producer] | None = None,
    config: GateConfig | None = None,
    clock: Callable[[], datetime] = _now,
) -> dict[str, int]:
    """Один проход прогрева: поводы → по человеку один, самый важный → ``dispatch`` через общий допуск.
    Сбой повода или человека не мешает остальным; общий флаг выключен — ничего не читаем и не шлём."""
    counts: dict[str, int] = {}
    try:
        cfg = config or GateConfig.from_settings(family=FAMILY_WARM)
        if not cfg.enabled or cfg.family != FAMILY_WARM:
            return counts
        producers = PRODUCERS if producers is None else producers
        active = [k for k in producers if k in cfg.kinds and k in KIND_POLICY]
    except Exception:  # noqa: BLE001
        logger.warning("warm tick: setup failed", exc_info=True)
        return {"error": 1}
    if not active:
        return counts

    by_person: dict[int, list[Proposal]] = {}
    for kind in active:
        try:
            async with session_factory() as session:
                proposals = await producers[kind](session, now=now)
        except Exception:  # noqa: BLE001 — упавший повод не мешает остальным
            logger.warning("warm producer %s failed", kind, exc_info=True)
            counts["producer_errors"] = counts.get("producer_errors", 0) + 1
            continue
        for proposal in proposals:
            if proposal.notice.kind != kind or not isinstance(proposal.notice, WarmNotice):
                counts["kind_mismatch"] = counts.get("kind_mismatch", 0) + 1
                await write_journal(
                    session_factory,
                    tick_at=now,
                    player_key=int(proposal.notice.player_key),
                    phase=UNKNOWN_PHASE,
                    kind=kind,
                    decision="error",
                    reason="kind_mismatch",
                )
                continue
            by_person.setdefault(proposal.notice.player_key, []).append(proposal)

    for person, proposals in sorted(by_person.items()):
        chosen = min(proposals, key=_priority)
        try:
            outcome = await dispatch(
                session_factory,
                chosen,
                phase=PHASES.get(chosen.notice.kind, UNKNOWN_PHASE),
                tick_at=now,
                send=send,
                config=cfg,
                clock=clock,
                store=WARM_STORE,
            )
        except Exception:  # noqa: BLE001
            logger.warning("warm tick: person %s failed", person, exc_info=True)
            outcome = Outcome("error", "tick")
        key = outcome.result if outcome.decision == "send" else outcome.decision
        counts[key or "skip"] = counts.get(key or "skip", 0) + 1
    return counts


async def run_pass(*, now: datetime | None = None) -> dict[str, int]:
    """Фоновая точка входа: свой ``Bot`` клиентского бота на проход (создаётся только при первой отправке
    и закрывается здесь же). Общий бот цикла матчей не трогаем: он закрывается в конце своего прохода."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    from src.infrastructure.db.session import async_session_factory
    from src.shared.config import Settings

    bot: Bot | None = None

    async def send(chat_id: int, body: str, buttons: list[list[dict]]) -> str:
        nonlocal bot
        if bot is None:
            token = (Settings().telegram_bot_token_client or "").strip()  # type: ignore[call-arg]
            if not token:
                return hn.FAILED
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        return await hn.send_via_client_bot(chat_id, body, buttons, detect_gone=True, bot=bot)

    try:
        return await run_tick(async_session_factory, now=now or _now(), send=send)
    finally:
        if bot is not None:
            await bot.session.close()


# Сутки/недели в ``warm_notices`` нужны, пока защищают от повтора; разовые (``once``) хранятся всегда:
# второго приветствия и второго напоминания не бывает.
NOTICES_KEEP = timedelta(days=90)
_DELETE_OLD = text("DELETE FROM warm_notices WHERE ref <> 'once' AND created_at < :cutoff")


async def cleanup_old_notices(session_factory, *, now: datetime) -> int:
    try:
        async with session_factory() as session:
            result = await session.execute(_DELETE_OLD, {"cutoff": _utc(now) - NOTICES_KEEP})
            await session.commit()
        return int(getattr(result, "rowcount", 0) or 0)
    except Exception:  # noqa: BLE001
        logger.warning("warm cleanup failed", exc_info=True)
        return 0


__all__ = [
    "CB_OFF",
    "CB_ON",
    "CB_SUB",
    "PRODUCERS",
    "WARM_STORE",
    "KnownVisitor",
    "WarmNotice",
    "clear_blocked",
    "cleanup_old_notices",
    "nudge_due",
    "off_button",
    "on_button",
    "parse_subscribe_callback",
    "run_pass",
    "run_tick",
    "set_opt_out",
    "single_visit_known",
    "subscribe_callback",
]
