"""«Кто кого»: единая точка допуска отправки игроку (TASK-426, срез 0).

Все правила «можно ли сейчас писать этому человеку» живут здесь и больше нигде:

* тихие часы 23:00–09:00 по Минску;
* дневной бюджет (1 сообщение в сутки по Минску) и недельный (3 за последние 7 суток по Минску);
* пауза игрока, «не присылать» (``remind``), отключённый тип, блокировка бота;
* выключатели новых поводов: общий флаг, флаг повода, белый список, «тексты приняты», сухой прогон.

Прежние поводы (итог хода, ``moved``, ``rescore``, ``nomove``, ``mfinal``, ``overtook``) проходят ту же проверку
со своей политикой: итоги и события вне бюджета, как раньше; ``nomove``/``mfinal``/``overtook`` — в дневном, но
без недельного лимита, чтобы поведение не изменилось. Недельный лимит и выключатели действуют на новые поводы.

Закрыто по умолчанию: повод, которого нет в ``KIND_POLICY``, и любая ошибка внутри проверки — отказ с причиной.
Модуль не отправляет и ничего не пишет: его зовёт отправитель (``hockey_notices.deliver``, ``kk_notify.dispatch``)
прямо перед занятием строки и вызовом Telegram, поэтому состояние читается заново, а не из списка, собранного раньше.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.hockey_sources import MINSK_TZ

logger = logging.getLogger(__name__)

QUIET_FROM, QUIET_TO = 23, 9
DAILY_CAP = 1
WEEKLY_CAP = 3
WEEK_DAYS = 7  # сегодняшние сутки по Минску и шесть предыдущих

# Причины отказа (пишутся в журнал как есть).
UNKNOWN_KIND = "unknown_kind"
DISABLED = "disabled"
KIND_OFF = "kind_off"
TEXTS_NOT_ACCEPTED = "texts_not_accepted"
BLOCKED = "blocked"
OPTED_OUT = "opted_out"
TYPE_OFF = "type_off"
PAUSED = "paused"
QUIET = "quiet_hours"
DAILY_LIMIT = "daily_cap"
WEEKLY_LIMIT = "weekly_cap"
DRY_RUN = "dry_run"
OK = "ok"
STALE_PREFIX = "stale:"
ERROR_PREFIX = "error:"


@dataclass(frozen=True)
class KindPolicy:
    # Входит в дневной бюджет (и считается в нём). Итоги и события — нет.
    budgeted: bool
    # Действует и недельный лимит.
    weekly: bool = False
    # Новый повод: нужны общий флаг, флаг повода, белый список; пауза игрока.
    new: bool = False
    # Колонка ``hockey_player_prefs`` с отключением этого типа (None — отдельной нет, есть только ``remind``).
    type_column: str | None = None
    # Меньше — важнее, когда у игрока в один проход несколько кандидатов.
    priority: int = 100


KIND_POLICY: dict[str, KindPolicy] = {
    # Прежние поводы: поведение сохранено.
    "result": KindPolicy(budgeted=False, type_column="notify_result"),
    "moved": KindPolicy(budgeted=False),
    "mvfree": KindPolicy(budgeted=False),
    "rescore": KindPolicy(budgeted=False, type_column="notify_result"),
    "mfinal": KindPolicy(budgeted=True, type_column="notify_mfinal", priority=0),
    "overtook": KindPolicy(budgeted=True, type_column="notify_overtook", priority=1),
    "nomove": KindPolicy(budgeted=True, type_column="notify_nomove", priority=2),
}
# Новые поводы регистрируются в срезах 2–4 через ``register_kind``; пока их нет.


def register_kind(kind: str, policy: KindPolicy) -> None:
    if not policy.new:
        raise ValueError("register_kind принимает только новые поводы (new=True)")
    KIND_POLICY[kind] = policy


def _csv(raw: str | None) -> list[str]:
    return [p.strip() for p in (raw or "").split(",") if p.strip()]


@dataclass(frozen=True)
class GateConfig:
    enabled: bool = False
    dry_run: bool = True
    texts_accepted: bool = False
    kinds: frozenset[str] = field(default_factory=frozenset)
    whitelist: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_settings(cls, settings=None) -> "GateConfig":
        if settings is None:
            from src.shared.config import Settings

            settings = Settings()  # type: ignore[call-arg]
        keys: set[int] = set()
        for part in _csv(getattr(settings, "kk_notify_whitelist", "")):
            try:
                keys.add(int(part))
            except ValueError:
                logger.warning("kk_notify whitelist: %r не число, пропущено", part)
        return cls(
            enabled=bool(getattr(settings, "kk_notify_enabled", False)),
            dry_run=bool(getattr(settings, "kk_notify_dry_run", True)),
            texts_accepted=bool(getattr(settings, "kk_notify_texts_accepted", False)),
            kinds=frozenset(p.lower() for p in _csv(getattr(settings, "kk_notify_kinds", ""))),
            whitelist=frozenset(keys),
        )


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str = OK
    dry_run: bool = False


# Проверка свежести повода прямо перед отправкой: ``None`` — всё ещё актуально, иначе причина (без префикса).
Recheck = Callable[[AsyncSession, int, datetime], Awaitable["str | None"]]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _local(value: datetime) -> datetime:
    return _utc(value).astimezone(MINSK_TZ)


def in_quiet_hours(now: datetime) -> bool:
    hour = _local(now).hour
    return hour >= QUIET_FROM or hour < QUIET_TO


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Сутки по Минску, в которые попадает ``now``, — в UTC."""
    start = _local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def week_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Окно недельного лимита: сегодняшние сутки по Минску и шесть предыдущих — в UTC."""
    day_start, day_end = day_bounds(now)
    return day_start - timedelta(days=WEEK_DAYS - 1), day_end


_PREFS = text("""
    SELECT COALESCE(pr.remind, true) AS remind, pr.bot_blocked_at, pr.notify_paused_until,
           COALESCE(pr.notify_nomove, true) AS notify_nomove, COALESCE(pr.notify_result, true) AS notify_result,
           COALESCE(pr.notify_overtook, true) AS notify_overtook, COALESCE(pr.notify_mfinal, true) AS notify_mfinal
    FROM (SELECT CAST(:player_key AS BIGINT) AS player_key) AS q
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = q.player_key
    """)

# Сообщения, что уже ушли или заняты и ещё в пути, за окно. Итоги и события в бюджет не входят.
_SPENT = text("""
    SELECT COUNT(*) FROM hockey_notices
    WHERE player_key = :player_key AND NOT (kind = ANY(:exempt))
      AND ((sent_at >= :since AND sent_at < :until)
           OR (sent_at IS NULL AND NOT failed AND created_at >= :since AND created_at < :until))
    """)


async def _spent(session: AsyncSession, player_key: int, since: datetime, until: datetime) -> int:
    exempt = [k for k, p in KIND_POLICY.items() if not p.budgeted]
    params = {"player_key": player_key, "exempt": exempt, "since": since, "until": until}
    return int((await session.execute(_SPENT, params)).scalar_one())


async def admit(
    session: AsyncSession,
    *,
    kind: str,
    player_key: int,
    now: datetime,
    config: GateConfig | None = None,
    recheck: Recheck | None = None,
) -> Admission:
    """Можно ли прямо сейчас отправить ``kind`` игроку ``player_key``. Любая ошибка — отказ."""
    try:
        return await _admit(session, kind=kind, player_key=player_key, now=now, config=config, recheck=recheck)
    except Exception as exc:  # noqa: BLE001 — закрыто по умолчанию: сомнение значит «не писать»
        logger.warning("kk_notify gate error for %s/%s", kind, player_key, exc_info=True)
        return Admission(False, f"{ERROR_PREFIX}{type(exc).__name__}")


async def _admit(
    session: AsyncSession,
    *,
    kind: str,
    player_key: int,
    now: datetime,
    config: GateConfig | None,
    recheck: Recheck | None,
) -> Admission:
    policy = KIND_POLICY.get(kind)
    if policy is None:
        return Admission(False, UNKNOWN_KIND)
    cfg = config
    if policy.new:
        cfg = cfg or GateConfig.from_settings()
        if not cfg.enabled:
            return Admission(False, DISABLED)
        if kind not in cfg.kinds:
            return Admission(False, KIND_OFF)
        # Тексты не приняты: только белый список. Сухой прогон ничего не отправляет, поэтому его аудитория не режется.
        if not cfg.texts_accepted and player_key not in cfg.whitelist and not cfg.dry_run:
            return Admission(False, TEXTS_NOT_ACCEPTED)

    prefs = (await session.execute(_PREFS, {"player_key": player_key})).one()
    if prefs.bot_blocked_at is not None:
        return Admission(False, BLOCKED)
    if not prefs.remind:
        return Admission(False, OPTED_OUT)
    if policy.type_column is not None and not getattr(prefs, policy.type_column):
        return Admission(False, TYPE_OFF)
    if policy.new and prefs.notify_paused_until is not None and _utc(prefs.notify_paused_until) > _utc(now):
        return Admission(False, PAUSED)

    if in_quiet_hours(now):
        return Admission(False, QUIET)

    if policy.budgeted:
        day_start, day_end = day_bounds(now)
        if await _spent(session, player_key, day_start, day_end) >= DAILY_CAP:
            return Admission(False, DAILY_LIMIT)
        if policy.weekly:
            week_start, week_end = week_bounds(now)
            if await _spent(session, player_key, week_start, week_end) >= WEEKLY_CAP:
                return Admission(False, WEEKLY_LIMIT)

    if recheck is not None:
        stale = await recheck(session, player_key, now)
        if stale:
            return Admission(False, f"{STALE_PREFIX}{stale}")

    if policy.new and cfg is not None and cfg.dry_run:
        return Admission(False, DRY_RUN, dry_run=True)
    return Admission(True, OK)


__all__ = [
    "Admission",
    "DAILY_CAP",
    "GateConfig",
    "KIND_POLICY",
    "KindPolicy",
    "QUIET_FROM",
    "QUIET_TO",
    "Recheck",
    "WEEKLY_CAP",
    "admit",
    "day_bounds",
    "in_quiet_hours",
    "register_kind",
    "week_bounds",
]
