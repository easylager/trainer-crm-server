"""«Кто кого»: поводы новых уведомлений игрокам (TASK-426, срезы 2–4).

Повод — производитель: смотрит в базу и предлагает ``Proposal`` по каждому подходящему игроку. Он ничего не
отправляет и не пишет; отправка идёт через ``kk_notify.dispatch`` и единую точку допуска (лимиты, тихие часы,
«не присылать», флаги, согласие). Условия повода здесь сужают кандидатов, но не заменяют допуск и перепроверку
перед отправкой (``recheck``): за секунды до вызова Telegram матч, ход, согласие и окно времени читаются заново.

Поводы (тексты — ``kk_notify_texts`` и ``copy_ru.json``, утверждены владельцем):

* ``invite`` — матч «своей» команды сегодня или завтра, хода нет: утро 09:00–11:00 по Минску, до матча не меньше
  3 часов; только активным игрокам.
* ``comeback`` — возврат на 3, 10 и 30 сутки молчания (одна попытка на ступень, всего не больше трёх за период
  молчания; ход обнуляет счёт); матч в ближайшие 6 суток без хода; после 30-х суток не планируем.
* ``week`` — итог недели, понедельник утром, активным: засчитанный ход за неделю и очки больше нуля; не в первое
  число месяца (там итог месяца).
* ``month`` — итог месяца, 1-го числа с 10:00: месяц закрыт, итогов на правке нет, у игрока были засчитанные очки.
* ``consent`` — вопрос «Присылать?» после первого хода, один раз.

Паузу «два приглашения подряд без хода в течение суток — на месяц» выставляет ``apply_silence_pause``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application import hockey_notices as hn
from src.application import kk_notify_texts as tx
from src.application.hockey_slices import club_scope, month_period, slice_rows
from src.application.kk_notify import Producer, Proposal, match_still_open
from src.application.kk_notify_gate import (
    KIND_COMEBACK,
    KIND_CONSENT,
    KIND_INVITE,
    KIND_MONTH,
    KIND_WEEK,
    day_bounds,
)
from src.application.kk_notify_phase import Phase, PlayerFacts, days_since, load_one, load_player_facts
from src.ingestion.hockey_sources import MINSK_TZ
from src.shared.copy_ru import t

logger = logging.getLogger(__name__)

MORNING_FROM, MORNING_TO = 9, 11  # окно утренних сообщений по Минску: [9:00, 11:00)
MONTH_FROM = 10  # итог месяца — с 10:00 первого числа
MONTH_CATCHUP_TO = 11  # догон: 2-го числа до 11:00, если 1-го отправка не состоялась (отказ допуска, сбой)
INVITE_MIN_LEFT = timedelta(hours=3)
MATCH_MIN_LEFT = hn.NOMOVE_MIN_LEFT  # для строки матча в итогах и возвратах
COMEBACK_HORIZON = timedelta(days=6)
LINE_HORIZON = timedelta(days=14)  # «ближайший матч» в итогах
# Ступени возврата: (с какого дня молчания, до какого не включая). После 30-х суток не планируем.
COMEBACK_STEPS = ((3, 10), (10, 30), (30, 31))
PAUSE_DAYS = 30
PAUSE_AFTER_SILENT = 2  # приглашений подряд без хода в течение суток
PICK_WINDOW = timedelta(hours=24)


def _local(value: datetime) -> datetime:
    return hn._utc(value).astimezone(MINSK_TZ)


def in_window(now: datetime, start_hour: int, end_hour: int | None) -> bool:
    hour = _local(now).hour
    return hour >= start_hour and (end_hour is None or hour < end_hour)


def _all_of(*checks):
    async def check(session, player_key, now):
        for one in checks:
            reason = await one(session, player_key, now)
            if reason:
                return reason
        return None

    return check


def month_window(now: datetime) -> bool:
    """Итог месяца: 1-го числа с 10:00 и догоняющий проход 2-го до 11:00."""
    local = _local(now)
    return (local.day == 1 and local.hour >= MONTH_FROM) or (local.day == 2 and local.hour < MONTH_CATCHUP_TO)


async def _month_window_check(session, player_key, now):
    return None if month_window(now) else "out_of_window"


def _window_check(start_hour: int, end_hour: int | None):
    async def check(session, player_key, now):
        return None if in_window(now, start_hour, end_hour) else "out_of_window"

    return check


# ---------- общие запросы ----------

_NEXT_MATCH = text("""
    SELECT m.id AS match_id, m.home_team AS home, m.away_team AS away, m.starts_at,
           EXISTS (SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id AND p.player_key = :player_key) AS has_pick
    FROM game_matches AS m
    WHERE m.status = 'scheduled' AND m.starts_at >= :from_ AND m.starts_at < :until
      AND (CAST(:club AS text) IS NULL OR m.home_team = :club OR m.away_team = :club)
      AND (NOT CAST(:free AS BOOLEAN) OR NOT EXISTS (
            SELECT 1 FROM hockey_picks AS p WHERE p.match_id = m.id AND p.player_key = :player_key))
      AND (NOT CAST(:fresh AS BOOLEAN) OR NOT EXISTS (
            SELECT 1 FROM hockey_notices AS n
            WHERE n.player_key = :player_key AND n.match_id = m.id AND n.kind = 'comeback'))
    ORDER BY m.starts_at, m.id
    LIMIT 1
    """)


async def next_match(
    session: AsyncSession,
    player_key: int,
    *,
    club: str | None,
    from_: datetime,
    until: datetime,
    free: bool,
    fresh: bool = False,
) -> dict | None:
    """Ближайший запланированный матч клуба (``club=None`` — любой). ``free`` — только без хода игрока,
    ``fresh`` — которого ему ещё не предлагали возвратом."""
    row = (
        await session.execute(
            _NEXT_MATCH,
            {
                "player_key": player_key,
                "club": club,
                "from_": hn._utc(from_),
                "until": hn._utc(until),
                "free": free,
                "fresh": fresh,
            },
        )
    ).one_or_none()
    return dict(row._mapping) if row else None


async def _slice(session: AsyncSession, cache: dict, club: str | None, period):
    key = (club, period.key)
    if key not in cache:
        cache[key] = await slice_rows(session, scope=club_scope(club), period=period)
    return cache[key]


async def _place(session, cache, player_key: int, club: str | None, period) -> tuple[int, int] | None:
    """(место, всего) игрока в срезе клуба за месяц, если у него там есть очки."""
    if club is None:
        return None
    rows = await _slice(session, cache, club, period)
    mine = next((r for r in rows if r.player_key == player_key), None)
    if mine is None or mine.points <= 0:
        return None
    return mine.rank, len(rows)


def _buttons(match: dict | None) -> list[list[dict]]:
    rows: list = []
    if match is not None:
        rows.append(list(hn.pick_buttons(match["match_id"], match["home"], match["away"])))
    start = f"{hn.START_PICK}_{match['match_id']}" if match is not None else hn.START_PICK
    rows.append([hn.url_button(t("kk_notify.btn.table"), start)])
    rows.append(off_all_button())
    return hn._rows(*rows)


def off_all_button() -> list[dict]:
    """«Не присылать» — выключает все новые сообщения игры (не итог хода)."""
    return [{"text": t("kk_notify.btn.no"), "callback_data": CB_NOALL}]


CB_NOALL = "kk:noall"
CB_YES = "kk:yes"


async def _facts(
    session: AsyncSession, now: datetime, phases: set[Phase], *, consented: bool = True
) -> list[PlayerFacts]:
    out = []
    for f in await load_player_facts(session, as_of=now):
        if f.phase(now) not in phases:
            continue
        if consented and f.consent is not True:
            continue
        out.append(f)
    return out


# ---------- 1. матч сегодня или завтра, хода нет ----------


async def produce_invite(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not in_window(now, MORNING_FROM, MORNING_TO):
        return []
    out: list[Proposal] = []
    until = day_bounds(now)[1] + timedelta(days=1)  # конец завтрашних суток
    for f in await _facts(session, now, {Phase.ACTIVE}):
        club = await hn.fan_club(session, f.player_key, now=now)
        if club is None:
            continue
        m = await next_match(session, f.player_key, club=club, from_=now + INVITE_MIN_LEFT, until=until, free=True)
        if m is None:
            continue

        def render(sent_now, m=m):
            return tx.invite_text(home=m["home"], away=m["away"], starts_at=m["starts_at"], now=sent_now)

        notice = hn.Notice(
            KIND_INVITE,
            f.player_key,
            m["match_id"],
            render(now),
            _buttons(m),
        )
        out.append(
            Proposal(
                notice,
                _all_of(
                    _window_check(MORNING_FROM, MORNING_TO),
                    match_still_open(m["match_id"], min_left=INVITE_MIN_LEFT),
                ),
                render,
            )
        )
    return out


# ---------- 2. возврат ----------

_COMEBACKS_SINCE = text("""
    SELECT COUNT(*) FROM hockey_notices
    WHERE player_key = :player_key AND kind = 'comeback'
      AND (sent_at > :since OR (sent_at IS NULL AND created_at > :since))  -- занято или окончательно не ушло: попытка
    """)


def comeback_step(days_silent: int) -> int | None:
    """Номер ступени возврата (1–3) для числа суток молчания или ``None``: между ступенями и после 30-х — тишина."""
    for number, (first, last) in enumerate(COMEBACK_STEPS, start=1):
        if first <= days_silent < last:
            return number
    return None


def _comeback_still_due(step: int):
    """Перед отправкой: молчание всё ещё на этой ступени (не было хода на другой матч), попытки не исчерпаны."""

    async def check(session, player_key, now):
        facts = await load_one(session, player_key, as_of=now)
        if facts is None or facts.last_pick_at is None:
            return "no_facts"
        if comeback_step(days_since(facts.last_pick_at, now)) != step:
            return "step_changed"
        done = (
            await session.execute(_COMEBACKS_SINCE, {"player_key": player_key, "since": hn._utc(facts.last_pick_at)})
        ).scalar_one()
        return "step_done" if done >= step else None

    return check


async def produce_comeback(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not in_window(now, MORNING_FROM, MORNING_TO):
        return []
    out: list[Proposal] = []
    cache: dict = {}
    month = month_period(_local(now).date())
    for f in await _facts(session, now, {Phase.ACTIVE, Phase.COOLING, Phase.LOST}):
        if f.last_pick_at is None:
            continue
        step = comeback_step(days_since(f.last_pick_at, now))
        if step is None:
            continue
        # Попыток за период молчания (после последнего хода) — не больше трёх, по одной на ступень.
        done = (
            await session.execute(_COMEBACKS_SINCE, {"player_key": f.player_key, "since": hn._utc(f.last_pick_at)})
        ).scalar_one()
        if done >= step:
            continue
        club = await hn.fan_club(session, f.player_key, now=now)
        m = await next_match(
            session,
            f.player_key,
            club=club,
            from_=now + MATCH_MIN_LEFT,
            until=now + COMEBACK_HORIZON,
            free=True,
            fresh=True,
        )
        if m is None:
            continue
        place_text = None
        if step == 2:  # к десятидневному добавляется место — только по правилу места
            place = await _place(session, cache, f.player_key, club, month)
            if place is not None and club is not None:
                place_text = tx.place_line(club=club, month=month_idx(now), rank=place[0], size=place[1])

        def render(sent_now, m=m, place_text=place_text):
            return tx.comeback_text(
                home=m["home"], away=m["away"], starts_at=m["starts_at"], now=sent_now, place_line_text=place_text
            )

        out.append(
            Proposal(
                hn.Notice(KIND_COMEBACK, f.player_key, m["match_id"], render(now), _buttons(m)),
                _all_of(
                    _window_check(MORNING_FROM, MORNING_TO),
                    _comeback_still_due(step),
                    match_still_open(m["match_id"], min_left=MATCH_MIN_LEFT),
                ),
                render,
            )
        )
    return out


def month_idx(now: datetime) -> int:
    return _local(now).month


# ---------- 3. итог недели ----------

_WEEK_STATS = text("""
    SELECT p.player_key, COUNT(*)::int AS moves, SUM(p.points * (1 + p.doubled::int))::int AS points,
           (ARRAY_AGG(m.id ORDER BY m.starts_at DESC, m.id DESC))[1] AS anchor
    FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.points IS NOT NULL AND m.status = 'final' AND m.starts_at >= :since AND m.starts_at < :until
    GROUP BY p.player_key
    """)


def week_bounds_before(now: datetime) -> tuple[datetime, datetime]:
    """Прошедшая неделя: с понедельника 00:00 по Минску до понедельника 00:00 текущей недели — в UTC."""
    local = _local(now)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (monday - timedelta(days=7)).astimezone(timezone.utc), monday.astimezone(timezone.utc)


async def produce_week(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    local = _local(now)
    if local.weekday() != 0 or local.day == 1 or not in_window(now, MORNING_FROM, MORNING_TO):
        return []
    since, until = week_bounds_before(now)
    stats = {r.player_key: r for r in (await session.execute(_WEEK_STATS, {"since": since, "until": until})).all()}
    if not stats:
        return []
    out: list[Proposal] = []
    cache: dict = {}
    month = month_period(local.date())
    for f in await _facts(session, now, {Phase.ACTIVE}):
        s = stats.get(f.player_key)
        if s is None or s.moves < 1 or (s.points or 0) <= 0:
            continue
        club = await hn.fan_club(session, f.player_key, now=now)
        place = await _place(session, cache, f.player_key, club, month)
        m = (
            await next_match(
                session, f.player_key, club=club, from_=now + MATCH_MIN_LEFT, until=now + LINE_HORIZON, free=False
            )
            if club
            else None
        )
        line_match = m if (m is not None and not m["has_pick"]) else None

        def render(sent_now, s=s, club=club, place=place, line_match=line_match):
            return tx.week_text(
                moves=s.moves,
                points=s.points,
                club=club,
                month=month_idx(sent_now),
                rank=place[0] if place else None,
                size=place[1] if place else None,
                match=line_match,
                now=sent_now,
            )

        recheck = _window_check(MORNING_FROM, MORNING_TO)
        if line_match is not None:
            recheck = _all_of(recheck, match_still_open(line_match["match_id"], min_left=MATCH_MIN_LEFT))
        out.append(
            Proposal(
                hn.Notice(KIND_WEEK, f.player_key, s.anchor, render(now), _buttons(line_match)),
                recheck,
                render,
            )
        )
    return out


# ---------- 4. итог месяца ----------

_MONTH_PLAYERS = text("""
    SELECT DISTINCT p.player_key FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.points IS NOT NULL AND m.starts_at >= :since AND m.starts_at < :until
    """)
_MONTH_ANCHOR = text("""
    SELECT m.id FROM hockey_picks AS p JOIN game_matches AS m ON m.id = p.match_id
    WHERE p.player_key = :player_key AND p.points IS NOT NULL AND m.starts_at >= :since AND m.starts_at < :until
    ORDER BY m.starts_at DESC, m.id DESC LIMIT 1
    """)
_MONTH_DONE = text("""
    SELECT 1 FROM hockey_notices WHERE player_key = :player_key AND match_id = :match_id AND kind = 'month'
    """)
_CLOSURE = text("""
    SELECT 1 FROM hockey_closures
    WHERE kind = 'month' AND period_start = :since AND club = :club AND league_id IS NULL
    """)
_UNFINISHED = text("""
    SELECT 1 FROM game_matches
    WHERE starts_at >= :since AND starts_at < :until AND (home_team = :club OR away_team = :club)
      AND status NOT IN ('final', 'cancelled') LIMIT 1
    """)
_PENDING_RESCORE = text(
    "SELECT 1 FROM hockey_notices WHERE kind = 'rescore' AND sent_at IS NULL AND NOT failed LIMIT 1"
)
_CROWNED = text("""
    SELECT player_key FROM hockey_crowns
    WHERE kind = 'month' AND period_start = :since AND club = :club AND league_id IS NULL
    """)


def previous_month(now: datetime):
    first = _local(now).date().replace(day=1)
    return month_period((first - timedelta(days=1)).replace(day=1))


async def _month_closed(session: AsyncSession, club: str, period) -> bool:
    params = {"since": period.since, "until": period.until, "club": club}
    if (await session.execute(_CLOSURE, params)).first() is None:
        return False
    if (await session.execute(_UNFINISHED, params)).first() is not None:
        return False
    return (await session.execute(_PENDING_RESCORE)).first() is None


def _month_recheck(club: str, period, match_check):
    async def check(session, player_key, now):
        if not await _month_closed(session, club, period):
            return "month_not_closed"
        return await match_check(session, player_key, now) if match_check else None

    return check


async def produce_month(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    if not month_window(now):
        return []
    period = previous_month(now)
    players = set(
        (await session.execute(_MONTH_PLAYERS, {"since": period.since, "until": period.until})).scalars().all()
    )
    if not players:
        return []
    out: list[Proposal] = []
    cache: dict = {}
    closed: dict[str, bool] = {}
    for f in await _facts(session, now, {Phase.ACTIVE, Phase.COOLING, Phase.LOST}):
        if f.player_key not in players:
            continue
        club = await hn.fan_club(session, f.player_key, now=period.until - timedelta(seconds=1))
        if club is None:
            continue
        if club not in closed:
            closed[club] = await _month_closed(session, club, period)
        if not closed[club]:
            continue
        rows = await _slice(session, cache, club, period)
        mine = next((r for r in rows if r.player_key == f.player_key), None)
        if mine is None or mine.points <= 0:
            continue
        crowned = set((await session.execute(_CROWNED, {"since": period.since, "club": club})).scalars().all())
        anchor = (
            await session.execute(
                _MONTH_ANCHOR, {"player_key": f.player_key, "since": period.since, "until": period.until}
            )
        ).scalar_one_or_none()
        if anchor is None:
            continue
        # Уже отправляли (или занято) — догон не шлёт второй раз: ключ строки тот же.
        if (await session.execute(_MONTH_DONE, {"player_key": f.player_key, "match_id": anchor})).first() is not None:
            continue
        m = await next_match(
            session, f.player_key, club=club, from_=now + MATCH_MIN_LEFT, until=now + LINE_HORIZON, free=True
        )
        month_number = _local(period.since).month

        def render(sent_now, mine=mine, club=club, crowned=crowned, rows=rows, m=m, month_number=month_number, f=f):
            return tx.month_text(
                month=month_number,
                club=club,
                points=mine.points,
                exact=mine.exact,
                rank=mine.rank,
                size=len(rows),
                crowned=len(crowned),
                i_am_crowned=f.player_key in crowned,
                match=m,
                now=sent_now,
            )

        match_check = match_still_open(m["match_id"], min_left=MATCH_MIN_LEFT) if m else None
        out.append(
            Proposal(
                hn.Notice(KIND_MONTH, f.player_key, anchor, render(now), _buttons(m)),
                _all_of(_month_window_check, _month_recheck(club, period, match_check)),
                render,
            )
        )
    return out


# ---------- 5. согласие после первого хода ----------

_FIRST_PICK = text("SELECT match_id FROM hockey_picks WHERE player_key = :player_key ORDER BY picked_at, id LIMIT 1")
_CONSENT_NOW = text("""
    SELECT pr.notify_consent, COALESCE(pr.remind, true) AS remind, pr.bot_blocked_at
    FROM (SELECT CAST(:player_key AS BIGINT) AS player_key) AS q
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = q.player_key
    """)


async def _consent_unanswered(session, player_key, now):
    row = (await session.execute(_CONSENT_NOW, {"player_key": player_key})).one()
    return None if row.notify_consent is None else "answered"


async def produce_consent(session: AsyncSession, *, now: datetime) -> list[Proposal]:
    out: list[Proposal] = []
    for f in await load_player_facts(session, as_of=now):
        if f.consent is not None or f.last_pick_at is None or f.phase(now) is Phase.OFF:
            continue
        anchor = (await session.execute(_FIRST_PICK, {"player_key": f.player_key})).scalar_one_or_none()
        if anchor is None:
            continue
        buttons = hn._rows(
            [
                {"text": t("kk_notify.btn.yes"), "callback_data": CB_YES},
                {"text": t("kk_notify.btn.no"), "callback_data": CB_NOALL},
            ]
        )
        out.append(
            Proposal(hn.Notice(KIND_CONSENT, f.player_key, anchor, tx.consent_text(), buttons), _consent_unanswered)
        )
    return out


# ---------- пауза после двух приглашений без хода ----------

_RECENT_INVITES = text("""
    SELECT n.player_key, n.sent_at, pr.notify_paused_until,
           EXISTS (SELECT 1 FROM hockey_picks AS p
                   WHERE p.player_key = n.player_key AND p.picked_at > n.sent_at
                     AND p.picked_at <= n.sent_at + INTERVAL '24 hours') AS picked
    FROM hockey_notices AS n
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = n.player_key
    WHERE n.kind IN ('invite', 'comeback') AND n.sent_at IS NOT NULL AND n.sent_at > :since
    ORDER BY n.player_key, n.sent_at DESC
    """)

_SET_PAUSE = text("""
    INSERT INTO hockey_player_prefs (player_key, notify_paused_until) VALUES (:player_key, :until)
    ON CONFLICT (player_key) DO UPDATE SET notify_paused_until = EXCLUDED.notify_paused_until, updated_at = now()
    """)


async def apply_silence_pause(session: AsyncSession, *, now: datetime) -> int:
    """Два последних приглашения (``invite``/``comeback``) игроку остались без хода в течение суток — пауза
    всех новых сообщений на ``PAUSE_DAYS``. Приглашение моложе суток не судим. Приглашения, отправленные до начала
    прошлой паузы, не считаются, иначе пауза включалась бы снова сразу после окончания. Возвращает число пауз."""
    now = hn._utc(now)
    by_player: dict[int, list] = {}
    for r in (await session.execute(_RECENT_INVITES, {"since": now - timedelta(days=90)})).all():
        by_player.setdefault(r.player_key, []).append(r)
    paused = 0
    for player_key, rows in by_player.items():
        last = rows[:PAUSE_AFTER_SILENT]
        if len(last) < PAUSE_AFTER_SILENT:
            continue
        until = last[0].notify_paused_until
        if until is not None and hn._utc(until) > now:
            continue  # уже на паузе
        floor = hn._utc(until) - timedelta(days=PAUSE_DAYS) if until is not None else None
        if any(hn._utc(r.sent_at) > now - PICK_WINDOW for r in last):
            continue  # последнее приглашение ещё не созрело
        if floor is not None and any(hn._utc(r.sent_at) <= floor for r in last):
            continue
        if any(r.picked for r in last):
            continue
        await session.execute(_SET_PAUSE, {"player_key": player_key, "until": now + timedelta(days=PAUSE_DAYS)})
        paused += 1
    return paused


PRODUCERS: dict[str, Producer] = {
    KIND_CONSENT: produce_consent,
    KIND_MONTH: produce_month,
    KIND_WEEK: produce_week,
    KIND_INVITE: produce_invite,
    KIND_COMEBACK: produce_comeback,
}

__all__ = [
    "CB_NOALL",
    "CB_YES",
    "COMEBACK_STEPS",
    "PRODUCERS",
    "apply_silence_pause",
    "comeback_step",
    "in_window",
    "off_all_button",
    "produce_comeback",
    "produce_consent",
    "produce_invite",
    "produce_month",
    "produce_week",
]
