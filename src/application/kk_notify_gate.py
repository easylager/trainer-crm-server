"""Единая точка допуска отправки человеку: «Кто кого» (TASK-426) и прогрев посетителей катков (TASK-428).

Все правила «можно ли сейчас писать этому человеку» живут здесь и больше нигде. Человек — это Telegram-аккаунт:
``player_key`` игры и ``telegram_id`` клиента катка — одно и то же число (пишет один клиентский бот), поэтому
бюджет, замок и тихие часы общие для обеих семей поводов (``KindPolicy.family``):

* тихие часы 23:00–09:00 по Минску;
* дневной бюджет (1 сообщение в сутки по Минску) и недельный (3 за последние 7 суток по Минску);
* пауза игрока, «не присылать» (``remind``), отключённый тип, блокировка бота;
* выключатели новых поводов: общий флаг, флаг повода, белый список, «тексты приняты», сухой прогон — у каждой
  семьи свои (``KK_NOTIFY_*`` и ``WARM_*``), конфиг чужой семьи — отказ.

Бюджет считается по всему, что человек получил от бота: строки ``hockey_notices`` (кроме итогов и событий),
``warm_notices`` и доставленные напоминания колокольчика катка (``client_ice_watch_deliveries``, сезонное
напоминание по ``last_notified_at``). Колокольчик сам допуск не проходит (ответ на явную подписку), но в бюджете
считается: игрок-подписчик суммарно получает не больше 1 сообщения в сутки и 3 в неделю от поводов с допуском.

Семья ``warm`` (TASK-428) не знает про ``remind``, согласие игры и паузы: её согласие — явная подписка на каток
(повод перепроверяет её перед отправкой) или единственное напоминание с «Не присылать». Её «Не присылать» —
``warm_prefs.opted_out_at``, блокировка — ``warm_prefs.bot_blocked_at`` или блокировка, замеченная игрой.

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
NO_CONSENT = "no_consent"
QUIET = "quiet_hours"
DAILY_LIMIT = "daily_cap"
WEEKLY_LIMIT = "weekly_cap"
DRY_RUN = "dry_run"
OK = "ok"
FAMILY_MISMATCH = "family_mismatch"
STALE_PREFIX = "stale:"
ERROR_PREFIX = "error:"


FAMILY_KK = "kk"
FAMILY_WARM = "warm"
# Префикс настроек каждой семьи: ``{prefix}_enabled``, ``_dry_run``, ``_texts_accepted``, ``_kinds``, ``_whitelist``.
FAMILY_SETTINGS_PREFIX = {FAMILY_KK: "kk_notify", FAMILY_WARM: "warm"}


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
    # Зависит ли от главного согласия ``remind``. «Лига продлена» — ответ на действие владельца лиги, а не
    # игровая рассылка, и пришла бы и тому, кто не включал напоминания (так было всегда); остальные — зависят.
    respects_remind: bool = True
    # Нужно ли согласие на новые сообщения (``notify_consent``: ответ на первое сообщение или согласие по умолчанию
    # для игравших до выкатки). Итоги и события его не требуют.
    needs_consent: bool = False
    # Семья поводов: ``kk`` — игра (настройки ``hockey_player_prefs``, флаги ``KK_NOTIFY_*``), ``warm`` — прогрев
    # посетителей катков (``warm_prefs``, флаги ``WARM_*``).
    family: str = FAMILY_KK


KIND_POLICY: dict[str, KindPolicy] = {
    # Прежние поводы: поведение сохранено.
    "result": KindPolicy(budgeted=False, type_column="notify_result"),
    "moved": KindPolicy(budgeted=False),
    "mvfree": KindPolicy(budgeted=False),
    "rescore": KindPolicy(budgeted=False, type_column="notify_result"),
    # «Лига продлена» — ответ на действие владельца лиги: вне бюджета и не зависит от согласия ``remind``
    # (письмо о лиге, в которой человек состоит, а не рассылка), но с тихими часами, блокировкой и отключением типа.
    "league": KindPolicy(budgeted=False, type_column="notify_league", respects_remind=False),
    "mfinal": KindPolicy(budgeted=True, type_column="notify_mfinal", priority=0, needs_consent=True),
    "overtook": KindPolicy(budgeted=True, type_column="notify_overtook", priority=1, needs_consent=True),
    "nomove": KindPolicy(budgeted=True, type_column="notify_nomove", priority=2, needs_consent=True),
}


# Названия видов — до 12 символов (колонка ``hockey_notices.kind``) и в CHECK миграции 0328.
KIND_INVITE = "invite"  # матч сегодня или завтра, хода нет
KIND_COMEBACK = "comeback"  # возврат: 3, 10, 30 дней молчания
KIND_WEEK = "week"  # итог недели
KIND_MONTH = "month"  # итог месяца
KIND_CONSENT = "consent"  # вопрос о согласии после первого хода


def register_kind(kind: str, policy: KindPolicy, *, allow_unbudgeted: bool = False) -> None:
    """Зарегистрировать новый повод. Он обязан быть в дневном и недельном лимитах; вне бюджета — только по явному флагу."""
    if not policy.new:
        raise ValueError("register_kind принимает только новые поводы (new=True)")
    if not (policy.budgeted and policy.weekly) and not allow_unbudgeted:
        raise ValueError("новый повод должен быть budgeted=True и weekly=True (исключение — allow_unbudgeted=True)")
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
    family: str = FAMILY_KK

    @classmethod
    def from_settings(cls, settings=None, *, family: str = FAMILY_KK) -> "GateConfig":
        prefix = FAMILY_SETTINGS_PREFIX[family]  # неизвестная семья — KeyError: закрыто
        if settings is None:
            from src.shared.config import Settings

            settings = Settings()  # type: ignore[call-arg]
        keys: set[int] = set()
        for part in _csv(getattr(settings, f"{prefix}_whitelist", "")):
            try:
                keys.add(int(part))
            except ValueError:
                logger.warning("%s whitelist: %r не число, пропущено", prefix, part)
        return cls(
            enabled=bool(getattr(settings, f"{prefix}_enabled", False)),
            dry_run=bool(getattr(settings, f"{prefix}_dry_run", True)),
            texts_accepted=bool(getattr(settings, f"{prefix}_texts_accepted", False)),
            kinds=frozenset(p.lower() for p in _csv(getattr(settings, f"{prefix}_kinds", ""))),
            whitelist=frozenset(keys),
            family=family,
        )


def consent_question_active(cfg: GateConfig) -> bool:
    """Вопрос «Присылать?» реально уходит игрокам: общий флаг, флаг повода, не сухой прогон, тексты приняты."""
    return cfg.enabled and KIND_CONSENT in cfg.kinds and not cfg.dry_run and cfg.texts_accepted


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
    SELECT COALESCE(pr.remind, true) AS remind, pr.bot_blocked_at, pr.notify_paused_until, pr.notify_consent,
           COALESCE(pr.notify_nomove, true) AS notify_nomove, COALESCE(pr.notify_result, true) AS notify_result,
           COALESCE(pr.notify_overtook, true) AS notify_overtook, COALESCE(pr.notify_mfinal, true) AS notify_mfinal,
           COALESCE(pr.notify_league, true) AS notify_league
    FROM (SELECT CAST(:player_key AS BIGINT) AS player_key) AS q
    LEFT JOIN hockey_player_prefs AS pr ON pr.player_key = q.player_key
    """)

# Сообщения, что уже ушли или заняты и ещё в пути, за окно — всё, что человек получил от клиентского бота:
# игра (кроме итогов и событий), прогрев и доставленные напоминания колокольчика катка.
_SPENT = text("""
    SELECT
      (SELECT COUNT(*) FROM hockey_notices
       WHERE player_key = :player_key AND NOT (kind = ANY(:exempt))
         AND ((sent_at >= :since AND sent_at < :until)
              OR (sent_at IS NULL AND NOT failed AND created_at >= :since AND created_at < :until)))
    + (SELECT COUNT(*) FROM warm_notices
       WHERE telegram_id = :player_key
         AND ((sent_at >= :since AND sent_at < :until)
              OR (sent_at IS NULL AND NOT failed AND created_at >= :since AND created_at < :until)))
    + (SELECT COUNT(*) FROM client_ice_watch_deliveries AS d
       JOIN client_ice_watches AS w ON w.id = d.watch_id
       WHERE w.telegram_id = :player_key AND d.ok AND d.attempted_at >= :since AND d.attempted_at < :until)
    + (SELECT COUNT(*) FROM client_ice_watches
       WHERE telegram_id = :player_key AND watch_kind = 'season_open'
         AND last_notified_at >= :since AND last_notified_at < :until)
    """)


async def _spent(session: AsyncSession, player_key: int, since: datetime, until: datetime) -> int:
    exempt = [k for k, p in KIND_POLICY.items() if not p.budgeted]
    params = {"player_key": player_key, "exempt": exempt, "since": since, "until": until}
    return int((await session.execute(_SPENT, params)).scalar_one())


# Новые поводы (TASK-426, срезы 2–4): все в дневном и недельном лимитах, под паузой игрока и под согласием, кроме
# самого вопроса о согласии. Приоритет внутри прохода: меньше — важнее.
register_kind(KIND_CONSENT, KindPolicy(budgeted=True, weekly=True, new=True, priority=0))
register_kind(KIND_MONTH, KindPolicy(budgeted=True, weekly=True, new=True, priority=1, needs_consent=True))
register_kind(KIND_WEEK, KindPolicy(budgeted=True, weekly=True, new=True, priority=2, needs_consent=True))
register_kind(KIND_INVITE, KindPolicy(budgeted=True, weekly=True, new=True, priority=3, needs_consent=True))
register_kind(KIND_COMEBACK, KindPolicy(budgeted=True, weekly=True, new=True, priority=4, needs_consent=True))


# Прогрев посетителей (TASK-428): те же правила и тот же бюджет. Приоритет внутри прохода: меньше — важнее.
KIND_WARM_WELCOME = "warm_welcome"  # сразу после подписки на каток, один раз
KIND_WARM_TODAY = "warm_today"  # утром в день сеанса на подписанном катке
KIND_WARM_WEEK = "warm_week"  # недельная подборка сеансов катка
KIND_WARM_NUDGE = "warm_nudge"  # одно напоминание тому, кто запускал бота и смотрел каток, но не подписан
# Порядок = приоритет: в четверг подборка недели важнее «сегодня» (в ней есть и сегодняшние сеансы).
WARM_KINDS = (KIND_WARM_WELCOME, KIND_WARM_WEEK, KIND_WARM_TODAY, KIND_WARM_NUDGE)
for _priority, _kind in enumerate(WARM_KINDS):
    register_kind(_kind, KindPolicy(budgeted=True, weekly=True, new=True, priority=_priority, family=FAMILY_WARM))

_WARM_PREFS = text("""
    SELECT wp.opted_out_at, COALESCE(wp.bot_blocked_at, hp.bot_blocked_at) AS bot_blocked_at
    FROM (SELECT CAST(:player_key AS BIGINT) AS k) AS q
    LEFT JOIN warm_prefs AS wp ON wp.telegram_id = q.k
    LEFT JOIN hockey_player_prefs AS hp ON hp.player_key = q.k
    """)


_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))")


async def lock_player(session: AsyncSession, player_key: int) -> None:
    """Замок на человека до конца транзакции: допуск и занятие строки идут под ним, так что два цикла (или процесса)
    не пройдут допуск по одному человеку одновременно. Один ключ для всех путей отправки и обеих семей поводов."""
    await session.execute(_LOCK, {"lock_key": f"kk_notify:{player_key}"})


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
        cfg = cfg or GateConfig.from_settings(family=policy.family)
        if cfg.family != policy.family:  # выключатели чужой семьи не открывают этот повод
            return Admission(False, FAMILY_MISMATCH)
        if not cfg.enabled:
            return Admission(False, DISABLED)
        if kind not in cfg.kinds:
            return Admission(False, KIND_OFF)
        # Тексты не приняты: только белый список. Сухой прогон ничего не отправляет, поэтому его аудитория не режется.
        if not cfg.texts_accepted and player_key not in cfg.whitelist and not cfg.dry_run:
            return Admission(False, TEXTS_NOT_ACCEPTED)

    if policy.family == FAMILY_WARM:
        warm = (await session.execute(_WARM_PREFS, {"player_key": player_key})).one()
        if warm.bot_blocked_at is not None:
            return Admission(False, BLOCKED)
        if warm.opted_out_at is not None:
            return Admission(False, OPTED_OUT)
        return await _limits(session, policy, kind=kind, player_key=player_key, now=now, cfg=cfg, recheck=recheck)

    prefs = (await session.execute(_PREFS, {"player_key": player_key})).one()
    if prefs.bot_blocked_at is not None:
        return Admission(False, BLOCKED)
    if policy.respects_remind and not prefs.remind:
        return Admission(False, OPTED_OUT)
    if policy.type_column is not None and not getattr(prefs, policy.type_column):
        return Admission(False, TYPE_OFF)
    if policy.needs_consent:
        consent = prefs.notify_consent
        if consent is False:
            return Admission(
                False, NO_CONSENT
            )  # нажал «Не присылать»: выключены все пуши игры, кроме итога хода и событий
        if consent is None:
            # Не спрашивали. Новые поводы без согласия не идут никогда. Прежние (nomove, mfinal, overtook) идут, пока
            # вопрос о согласии никому не задаётся (флаги выключены или сухой прогон): иначе новые игроки молча
            # потеряли бы пуши, которые у них работают сейчас. Как только вопрос реально уходит — нужен ответ.
            if policy.new:
                return Admission(False, NO_CONSENT)
            cfg = cfg or GateConfig.from_settings()
            if consent_question_active(cfg):
                return Admission(False, NO_CONSENT)
    if policy.new and prefs.notify_paused_until is not None and _utc(prefs.notify_paused_until) > _utc(now):
        return Admission(False, PAUSED)
    return await _limits(session, policy, kind=kind, player_key=player_key, now=now, cfg=cfg, recheck=recheck)


async def _limits(
    session: AsyncSession,
    policy: KindPolicy,
    *,
    kind: str,
    player_key: int,
    now: datetime,
    cfg: GateConfig | None,
    recheck: Recheck | None,
) -> Admission:
    """Общая часть для обеих семей: тихие часы, бюджеты, свежесть повода, сухой прогон."""
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
    "FAMILY_KK",
    "FAMILY_WARM",
    "WARM_KINDS",
    "GateConfig",
    "KIND_POLICY",
    "KindPolicy",
    "QUIET_FROM",
    "QUIET_TO",
    "Recheck",
    "WEEKLY_CAP",
    "admit",
    "lock_player",
    "day_bounds",
    "in_quiet_hours",
    "register_kind",
    "week_bounds",
]
