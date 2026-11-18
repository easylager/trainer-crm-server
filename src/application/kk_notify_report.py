"""«Кто кого»: недельный отчёт админу (TASK-426, срез 1). Только читает, игрокам ничего не шлёт.

Раз в неделю, в понедельник после 10:00 по Минску, одно сообщение в админ-бот: игроки по фазам, ушло и вернулось,
сколько писем ушло и не дошло по прежним видам, сколько человек заблокировало бота, доля приглашений с ходом
в течение суток. Если что-то вышло за порог, сверху добавляется блок «Что не так»; отдельной тревоги нет.

Окно — семь полных календарных суток по Минску перед понедельником отчёта; фазы считаются на 00:00 этого
понедельника и на 00:00 понедельника неделей раньше. Блокировки и «не присылать» известны только на сегодня
(истории в базе нет), поэтому выключенные игроки в обеих неделях стоят в «выключили» и в «ушли/вернулись» не попадают.

Пороги живут в одном месте — ``Settings.kk_report_*`` (переменные окружения, без релиза кода).
Отчёт «занимает» период строкой ``kk_notify_runs`` до отправки: повтор тика недельный отчёт не дублирует.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from src.application.kk_notify_phase import Phase, load_player_facts
from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

REPORT_NAME = "weekly_report"
REPORT_HOUR = 10
CLAIM_STALE = timedelta(minutes=10)  # считаем отправку зависшей и пробуем снова не раньше
MAX_ATTEMPTS = 3
NBSP = " "
# Приглашения, для которых считаем «ход в течение суток»; итоги и события приглашениями не являются.
INVITE_KINDS = ("nomove", "mfinal", "overtook", "invite", "comeback")
# Прежние виды, о которых отчёт отчитывается: подписи для админа.
KIND_LABELS = {
    "result": "итогов хода",
    "nomove": "«нет хода»",
    "overtook": "«тебя обошли»",
    "mfinal": "«последний матч месяца»",
    "moved": "«матч перенесли»",
    "mvfree": "«перенесли, козырь свободен»",
    "rescore": "поправок итога",
    "invite": "«матч сегодня или завтра»",
    "comeback": "возвратов",
    "week": "итогов недели",
    "month": "итогов месяца",
    "consent": "вопросов о согласии",
    "lginvite": "приглашений собрать лигу",
}
INVITE_LABELS = {
    "nomove": "«нет хода»",
    "mfinal": "«последний матч месяца»",
    "overtook": "«тебя обошли»",
    "invite": "«матч сегодня или завтра»",
    "comeback": "возврат",
}
MONTHS_GEN = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)  # fmt: skip


@dataclass(frozen=True)
class Thresholds:
    fail_share: float = 0.2
    fail_min_sample: int = 10
    drop_share: float = 0.33
    drop_min_base: int = 6
    stall_min_prev: int = 5

    @classmethod
    def from_settings(cls, settings=None) -> "Thresholds":
        if settings is None:
            from src.shared.config import Settings

            settings = Settings()  # type: ignore[call-arg]
        d = cls()
        return cls(
            fail_share=float(getattr(settings, "kk_report_fail_share", d.fail_share)),
            fail_min_sample=int(getattr(settings, "kk_report_fail_min_sample", d.fail_min_sample)),
            drop_share=float(getattr(settings, "kk_report_drop_share", d.drop_share)),
            drop_min_base=int(getattr(settings, "kk_report_drop_min_base", d.drop_min_base)),
            stall_min_prev=int(getattr(settings, "kk_report_stall_min_prev", d.stall_min_prev)),
        )


@dataclass(frozen=True)
class ReportData:
    week_start: datetime  # понедельник 00:00 по Минску, в UTC
    week_end: datetime
    phases_now: dict[str, int] = field(default_factory=dict)
    phases_prev: dict[str, int] = field(default_factory=dict)
    left: int = 0  # неделю назад не были отвалившимися, теперь отвалились
    returned: int = 0  # неделю назад остывали или отвалились, теперь активны
    sent: dict[str, int] = field(default_factory=dict)
    failed: dict[str, int] = field(default_factory=dict)
    sent_prev_total: int = 0
    blocked_players: int = 0
    # Матчи за отчётную неделю (кроме отменённых): нет матчей — тишина в рассылке не аномалия (межсезонье).
    matches_in_week: int = 0
    # Отказов допуска по недельному лимиту за неделю (записей журнала; повтор в течение часа не пишется заново).
    weekly_cap_refusals: int = 0
    invites: dict[str, tuple[int, int]] = field(default_factory=dict)  # kind -> (отправлено, с ходом за сутки)

    @property
    def sent_total(self) -> int:
        return sum(self.sent.values())

    @property
    def failed_total(self) -> int:
        return sum(self.failed.values())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def week_window(now: datetime) -> tuple[datetime, datetime]:
    """Понедельник 00:00 по Минску текущей недели и неделей раньше — в UTC. Отчёт покрывает [раньше, текущий)."""
    local = _utc(now).astimezone(MINSK_TZ)
    monday = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return (monday - timedelta(days=7)).astimezone(timezone.utc), monday.astimezone(timezone.utc)


def period_label(now: datetime) -> str:
    iso = _utc(now).astimezone(MINSK_TZ).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def report_due(now: datetime) -> bool:
    """Понедельник текущей недели, 10:00 по Минску, уже наступил."""
    _, monday = week_window(now)
    return _utc(now) >= monday + timedelta(hours=REPORT_HOUR)


# ---------- сбор ----------

_NOTICES_SENT = text("""
    SELECT kind, COUNT(*) AS n FROM hockey_notices
    WHERE sent_at >= :since AND sent_at < :until GROUP BY kind
    """)
_NOTICES_FAILED = text("""
    SELECT kind, COUNT(*) AS n FROM hockey_notices
    WHERE failed AND created_at >= :since AND created_at < :until
      -- блокировка бота — не сбой доставки: игроков, ставших недостижимыми, не считаем
      AND NOT EXISTS (SELECT 1 FROM hockey_player_prefs AS pr
                      WHERE pr.player_key = hockey_notices.player_key AND pr.bot_blocked_at IS NOT NULL)
    GROUP BY kind
    """)
_MATCHES = text("""
    SELECT COUNT(*) FROM game_matches WHERE starts_at >= :since AND starts_at < :until AND status <> 'cancelled'
    """)
_WEEKLY_CAP = text("""
    SELECT COUNT(*) FROM kk_notify_decisions WHERE reason = 'weekly_cap' AND tick_at >= :since AND tick_at < :until
      AND (kind IS NULL OR kind NOT LIKE 'warm\\_%')  -- журнал общий с прогревом посетителей (TASK-428)
    """)
_BLOCKED = text("""
    SELECT COUNT(*) FROM hockey_player_prefs WHERE bot_blocked_at >= :since AND bot_blocked_at < :until
    """)
_INVITES = text("""
    SELECT n.kind, COUNT(*) AS sent,
           COUNT(*) FILTER (WHERE EXISTS (
               SELECT 1 FROM hockey_picks AS p
               WHERE p.player_key = n.player_key AND p.picked_at > n.sent_at
                 AND p.picked_at <= n.sent_at + INTERVAL '24 hours')) AS picked
    FROM hockey_notices AS n
    WHERE n.kind = ANY(:kinds) AND n.sent_at >= :since AND n.sent_at < :until
    GROUP BY n.kind
    """)


async def collect(session, *, now: datetime) -> ReportData:
    start, end = week_window(now)
    prev_start = start - timedelta(days=7)
    window = {"since": start, "until": end}

    facts_now = await load_player_facts(session, as_of=end)
    facts_prev = {f.player_key: f for f in await load_player_facts(session, as_of=start)}
    phases_now: dict[str, int] = {}
    phases_prev: dict[str, int] = {}
    left = returned = 0
    for fact in facts_now:
        phase = fact.phase(end)
        phases_now[phase.value] = phases_now.get(phase.value, 0) + 1
        before = facts_prev.get(fact.player_key)
        if before is None:
            continue
        before_phase = before.phase(start)
        if before_phase is not Phase.OFF and phase is Phase.LOST and before_phase is not Phase.LOST:
            left += 1
        if before_phase in (Phase.COOLING, Phase.LOST) and phase is Phase.ACTIVE:
            returned += 1
    for fact in facts_prev.values():
        phase = fact.phase(start)
        phases_prev[phase.value] = phases_prev.get(phase.value, 0) + 1

    sent = {r.kind: int(r.n) for r in (await session.execute(_NOTICES_SENT, window)).all()}
    failed = {r.kind: int(r.n) for r in (await session.execute(_NOTICES_FAILED, window)).all()}
    prev_sent = sum(
        int(r.n) for r in (await session.execute(_NOTICES_SENT, {"since": prev_start, "until": start})).all()
    )
    blocked = int((await session.execute(_BLOCKED, window)).scalar_one())
    # Ход в течение суток считаем только по уже «созревшим» приглашениям: суток после отправки хватило.
    invites = {
        r.kind: (int(r.sent), int(r.picked))
        for r in (
            await session.execute(
                _INVITES, {"kinds": list(INVITE_KINDS), "since": start, "until": end - timedelta(days=1)}
            )
        ).all()
    }
    matches = int((await session.execute(_MATCHES, window)).scalar_one())
    capped = int((await session.execute(_WEEKLY_CAP, window)).scalar_one())
    return ReportData(
        matches_in_week=matches,
        weekly_cap_refusals=capped,
        week_start=start,
        week_end=end,
        phases_now=phases_now,
        phases_prev=phases_prev,
        left=left,
        returned=returned,
        sent=sent,
        failed=failed,
        sent_prev_total=prev_sent,
        blocked_players=blocked,
        invites=invites,
    )


# ---------- аномалии ----------


def percent(part: int, whole: int) -> int:
    return int(100 * part / whole + 0.5) if whole else 0


def detect_anomalies(data: ReportData, th: Thresholds) -> list[str]:
    """Что вышло за порог. Пустой список — отклонений нет. Пороги — только из ``th``."""
    out: list[str] = []
    if data.matches_in_week > 0 and data.sent_prev_total >= th.stall_min_prev and data.sent_total == 0:
        out.append(f"Рассылка встала: на прошлой неделе ушло {data.sent_prev_total}, на этой — ни одного сообщения.")
    attempts = data.sent_total + data.failed_total
    if attempts >= th.fail_min_sample and data.failed_total / attempts > th.fail_share:
        out.append(
            f"Не дошло {data.failed_total} из {attempts} ({percent(data.failed_total, attempts)}{NBSP}%), "
            f"порог {round(th.fail_share * 100)}{NBSP}%."
        )
    active_prev = data.phases_prev.get(Phase.ACTIVE.value, 0)
    active_now = data.phases_now.get(Phase.ACTIVE.value, 0)
    if active_prev >= th.drop_min_base and active_prev - active_now >= th.drop_share * active_prev:
        out.append(
            f"Активных было {active_prev}, стало {active_now}: меньше на {percent(active_prev - active_now, active_prev)}{NBSP}%."
        )
    return out


# ---------- текст ----------


def _range(start: datetime, end: datetime) -> str:
    first = start.astimezone(MINSK_TZ).date()
    last = (end - timedelta(seconds=1)).astimezone(MINSK_TZ).date()
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.day}–{last.day} {MONTHS_GEN[last.month - 1]}"
    return f"{first.day} {MONTHS_GEN[first.month - 1]} – {last.day} {MONTHS_GEN[last.month - 1]}"


def render_report(data: ReportData, th: Thresholds) -> str:
    p = data.phases_now
    total = sum(p.values())
    lines = [f"<b>«Кто кого»: неделя {_range(data.week_start, data.week_end)}</b>", ""]
    anomalies = detect_anomalies(data, th)
    if anomalies:
        lines.append("<b>Что не так</b>")
        lines += [f"— {a}" for a in anomalies]
        lines.append("")
    lines.append(
        f"Игроков {total}: активных {p.get('active', 0)}, остывают {p.get('cooling', 0)}, "
        f"отвалились {p.get('lost', 0)}, без хода {p.get('new', 0)}, выключили {p.get('off', 0)}."
    )
    lines.append(
        f"Неделей раньше активных было {data.phases_prev.get(Phase.ACTIVE.value, 0)}. "
        f"Отвалились за неделю: {data.left}. Вернулись: {data.returned}."
    )
    lines.append("")
    if data.sent:
        parts = [f"{KIND_LABELS.get(kind, kind)} {n}" for kind, n in sorted(data.sent.items(), key=lambda kv: -kv[1])]
        lines.append(f"Отправлено {data.sent_total}: " + ", ".join(parts) + ".")
    else:
        lines.append("Отправлено: ничего.")
    attempts = data.sent_total + data.failed_total
    if attempts:
        lines.append(f"Не дошло: {data.failed_total} из {attempts} ({percent(data.failed_total, attempts)}{NBSP}%).")
    lines.append(f"Заблокировали бота: {data.blocked_players}.")
    lines.append(
        f"Записей журнала об отказе по недельному лимиту: {data.weekly_cap_refusals} (повтор в течение часа не пишется)."
    )
    lines.append("")
    lines.append("Ход в течение суток после сообщения:")
    for kind in INVITE_KINDS:
        sent, picked = data.invites.get(kind, (0, 0))
        label = INVITE_LABELS[kind]
        if sent:
            lines.append(f"— {label}: {picked} из {sent} ({percent(picked, sent)}{NBSP}%)")
        else:
            lines.append(f"— {label}: не было сообщений")
    if not anomalies:
        lines += ["", "Отклонений от порогов нет."]
    return "\n".join(lines)


# ---------- отправка раз в неделю ----------

_CLAIM = text("""
    INSERT INTO kk_notify_runs (name, period, attempts, claimed_at) VALUES (:name, :period, 1, :now)
    ON CONFLICT (name, period) DO UPDATE
    SET attempts = kk_notify_runs.attempts + 1, claimed_at = :now
    WHERE kk_notify_runs.done_at IS NULL AND kk_notify_runs.attempts < :max_attempts
      AND kk_notify_runs.claimed_at <= :stale
    RETURNING attempts
    """)
_DONE = text("UPDATE kk_notify_runs SET done_at = :now WHERE name = :name AND period = :period")


async def _warm_section(session_factory, data: ReportData) -> str:
    """Блок прогрева посетителей (TASK-428) за ту же неделю. Его сбой отчёт игры не останавливает."""
    try:
        from src.application.warm_report import collect as warm_collect
        from src.application.warm_report import render_section

        async with session_factory() as session:
            warm = await warm_collect(session, since=data.week_start, until=data.week_end)
        return "\n\n" + render_section(warm)
    except Exception:  # noqa: BLE001
        logger.warning("kk weekly report: warm section failed", exc_info=True)
        return ""


async def send_weekly_report_if_due(
    session_factory,
    *,
    now: datetime,
    send: Callable[[str], Awaitable["bool | None"]],
    thresholds: Thresholds | None = None,
) -> str:
    """Отправить недельный отчёт админам, если пора и ещё не отправляли. Возвращает: not_due | claimed_elsewhere | sent | retry."""
    if not report_due(now):
        return "not_due"
    period = period_label(now)
    params = {"name": REPORT_NAME, "period": period}
    async with session_factory() as session:
        claimed = await session.execute(
            _CLAIM,
            {**params, "now": _utc(now), "stale": _utc(now) - CLAIM_STALE, "max_attempts": MAX_ATTEMPTS},
        )
        if claimed.first() is None:
            return "claimed_elsewhere"
        await session.commit()
    async with session_factory() as session:
        data = await collect(session, now=now)
    body = render_report(data, thresholds or Thresholds.from_settings())
    body += await _warm_section(session_factory, data)
    delivered = await send(body)
    if delivered is False:
        logger.warning("kk weekly report: delivery failed, will retry")
        return "retry"
    # ``None`` — админ-бот не настроен, текст ушёл в лог: повторять незачем.
    async with session_factory() as session:
        await session.execute(_DONE, {**params, "now": _utc(now)})
        await session.commit()
    return "sent"


__all__ = [
    "ReportData",
    "Thresholds",
    "collect",
    "detect_anomalies",
    "period_label",
    "render_report",
    "report_due",
    "send_weekly_report_if_due",
    "week_window",
]
