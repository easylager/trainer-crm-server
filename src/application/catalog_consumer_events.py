"""
Потребительская аналитика каталога: просмотры публички, клик «Открыть в Telegram», вход в мини-апп.

Отдельно от ``client_share_events`` (намерение отправить) и ``trainer_demand_events`` (Lead Mode).
Без PII: только ``actor_hash``.

TASK-189:

* **Актёр стабилен во времени.** ``actor_hash`` = HMAC-SHA256(``CATALOG_ACTOR_HMAC_SECRET``,
  telegram id | IP+UA) — без дня внутри, поэтому «недельные уникальные» больше не сумма дневных.
  Секрет обязателен: **без него хэши не пишутся вовсе** (fail closed) — ни ``SECRET_KEY``,
  ни литерал по умолчанию: хэш от telegram id с известным ключом перебирается за минуты.
* **Дедуп** — уникальный ``dedup_key`` (migration 0220) + ``INSERT … ON CONFLICT DO NOTHING``:
  вид | группа поверхности | актёр | сутки по Минску | город | арена. Шесть арен за день —
  шесть строк; вход в мини-апп по диплинку (shell + карточка арены) — одна строка.
* **Город** у входа в мини-апп выводится из арены / диплинка, если клиент его не прислал.
* **C-B (share→open)** считает только входы по ссылке, открытой из чата
  (:func:`is_share_attributed_deeplink_open`), а не голый ``catalog`` с ``/go`` и не переход
  по CTA публичной страницы.
* **Сопоставимый ряд** начинается с первой строки нового формата (``dedup_key IS NOT NULL``)
  или с ``CATALOG_METRICS_COMPARABLE_SINCE`` — см. :func:`metrics_comparable_since`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.catalog_deep_links import is_catalog_deep_link
from src.application.place_links import (
    CATALOG_START_ANY,
    SHARE_SRC_VALUES,
    is_valid_start_param,
    parse_catalog_start_param,
    parse_place_deep_link,
)
from src.shared.notification_hours import NOTIFICATION_TZ
from src.shared.ua_class import classify_user_agent  # noqa: F401  (re-export for telemetry)

logger = logging.getLogger(__name__)

ACTOR_HMAC_SECRET_ENV = "CATALOG_ACTOR_HMAC_SECRET"
COMPARABLE_SINCE_ENV = "CATALOG_METRICS_COMPARABLE_SINCE"
#: Короче — не секрет, а пароль «на глаз»: такой тоже не принимаем (fail closed).
ACTOR_HMAC_SECRET_MIN_LEN = 32
#: Сколько хранить сырые события каталога (TTL-цикл ice_scrape_ttl чистит старше).
CATALOG_CONSUMER_EVENTS_RETENTION_DAYS = 400

KIND_PUBLIC_PAGE_VIEW = "public_page_view"
KIND_PUBLIC_TELEGRAM_CTA = "public_telegram_cta"
KIND_MINIAPP_CATALOG_ENTRY = "miniapp_catalog_entry"
KIND_PUBLIC_CONTACT_CLICK = "public_contact_click"

CATALOG_CONSUMER_KINDS = (
    KIND_PUBLIC_PAGE_VIEW,
    KIND_PUBLIC_TELEGRAM_CTA,
    KIND_MINIAPP_CATALOG_ENTRY,
    KIND_PUBLIC_CONTACT_CLICK,
)

SURFACE_PLACE_PAGE = "place_page"
SURFACE_SELECTION_PAGE = "selection_page"
SURFACE_ICE_CITY_DAY = "ice_city_day"
SURFACE_MINIAPP_ICE = "miniapp_ice"
SURFACE_MINIAPP_ARENA = "miniapp_arena"
SURFACE_MINIAPP_SHELL = "miniapp_shell"

_MINIAPP_DEDUP_GROUP = "miniapp"

_missing_secret_logged = False

_PUBLIC_PAGE_VIEW_EXTRA_KEYS = frozenset({"s", "i", "src"})


def _actor_hmac_secret() -> bytes | None:
    """Секрет актёра или ``None`` — тогда хэш не считается (fail closed).

    В ``src/shared/config.py`` нет признака «прод» (ни ENV, ни APP_ENV): различать окружения
    было бы угадыванием. Поэтому правило одно для всех окружений: нет секрета ≥ 32 символов —
    нет псевдонимов и одна ошибка в лог. Тесты/дев задают свой явный секрет.
    """
    global _missing_secret_logged
    raw = (os.environ.get(ACTOR_HMAC_SECRET_ENV) or "").strip()
    if not raw:
        try:
            from src.shared.config import get_settings

            raw = (get_settings().catalog_actor_hmac_secret or "").strip()
        except Exception:  # noqa: BLE001 — скрипты без токенов ботов не должны падать
            raw = ""
    if len(raw) < ACTOR_HMAC_SECRET_MIN_LEN:
        if not _missing_secret_logged:
            logger.error(
                "%s is unset or shorter than %d chars: catalog actor hashes are NOT recorded "
                "(WAU/dedup off). Set it, e.g. `openssl rand -hex 32`.",
                ACTOR_HMAC_SECRET_ENV,
                ACTOR_HMAC_SECRET_MIN_LEN,
            )
            _missing_secret_logged = True
        return None
    return raw.encode("utf-8")


def _hmac_actor(prefix: str, payload: str) -> str | None:
    secret = _actor_hmac_secret()
    if secret is None:
        return None
    return hmac.new(secret, f"{prefix}|{payload}".encode(), hashlib.sha256).hexdigest()


def catalog_event_day_minsk(when: datetime | None = None) -> date:
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(ZoneInfo(NOTIFICATION_TZ)).date()


def minsk_day_start_utc(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo(NOTIFICATION_TZ)).astimezone(timezone.utc)


def public_actor_hash(*, client_ip: str | None, user_agent: str | None) -> str | None:
    if not client_ip and not user_agent:
        return None
    return _hmac_actor("pub", f"{(client_ip or '').strip()}|{(user_agent or '').strip()[:200]}")


def telegram_actor_hash(telegram_id: int | str) -> str | None:
    return _hmac_actor("tg", str(int(telegram_id)))


#: Служебные аккаунты владельца и партнёра. В спрос не входят — ни новые события, ни уже
#: записанные. Сайт ими не исключается: публичка знает только IP и браузер, не telegram id.
CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS = frozenset({1304982166, 7492839293, 326107164})
#: Порог замера 6 декабря: уникальные в табе «Лёд» Минска за месяц. На карточке — Telegram-аккаунты.
MINSK_MONTHLY_TELEGRAM_GOAL = 300
_RU_MONTHS = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def is_excluded_catalog_telegram(telegram_id: int | str | None) -> bool:
    if telegram_id is None:
        return False
    try:
        return int(telegram_id) in CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS
    except (TypeError, ValueError):
        return False


def excluded_catalog_actor_hashes() -> list[str]:
    """HMAC тех же id, которыми пишется мини-апп. Пусто, если секрет актёра не задан."""
    hashes: list[str] = []
    for telegram_id in sorted(CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS):
        actor = telegram_actor_hash(telegram_id)
        if actor:
            hashes.append(actor)
    return hashes


def _hash_exclusion_sql(column: str, hashes: list[str], prefix: str) -> tuple[str, dict[str, str]]:
    """Фрагмент ``AND (col IS NULL OR col NOT IN (...))``. NULL — анонимный веб, его оставляем."""
    if not hashes:
        return "", {}
    params = {f"{prefix}{i}": actor for i, actor in enumerate(hashes)}
    placeholders = ", ".join(f":{key}" for key in params)
    return f" AND ({column} IS NULL OR {column} NOT IN ({placeholders}))", params


def catalog_actor_exclusion_sql(column: str = "actor_hash") -> tuple[str, dict[str, str]]:
    return _hash_exclusion_sql(column, excluded_catalog_actor_hashes(), "ex_tg_")


def share_actor_exclusion_sql(
    *,
    since: datetime,
    until: datetime,
    column: str = "actor_hash",
) -> tuple[str, dict[str, str]]:
    """Хэш «Поделиться» включает день (UTC) и вид. Считаем все дни окна для служебных id."""
    from src.application.client_delight_metrics import share_actor_hash
    from src.infrastructure.db.models import CLIENT_SHARE_KINDS

    start = since.astimezone(timezone.utc).date() - timedelta(days=1)
    end = until.astimezone(timezone.utc).date() + timedelta(days=1)
    hashes: list[str] = []
    day = start
    while day <= end:
        for telegram_id in sorted(CATALOG_METRICS_EXCLUDED_TELEGRAM_IDS):
            for kind in CLIENT_SHARE_KINDS:
                actor = share_actor_hash(telegram_id, kind, day)
                if actor:
                    hashes.append(actor)
        day += timedelta(days=1)
    return _hash_exclusion_sql(column, hashes, "ex_sh_")


def event_dedup_hash(
    *,
    kind: str,
    surface: str,
    actor_hash: str | None,
    day: date,
    city_id: int | None = None,
    arena_id: int | None = None,
    variant: str | None = None,
) -> str | None:
    """Ключ дедупа. Вход в мини-апп — одна группа на все поверхности (shell / карточка / лёд).

    ``variant`` (канал шаринга ``src``) разводит просмотры одного актёра по разным каналам:
    иначе первый органический заход за сутки съедал бы атрибуцию последующих открытий по ссылке.
    Без ``variant`` ключ прежний — ряд метрик сопоставим.
    """
    if not actor_hash:
        return None
    group = _MINIAPP_DEDUP_GROUP if kind == KIND_MINIAPP_CATALOG_ENTRY else surface
    raw = f"{kind}|{group}|{actor_hash}|{day.isoformat()}|{city_id or 0}|{arena_id or 0}"
    if variant:
        raw += f"|{variant}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_share_deeplink_start_param(start_param: str | None) -> bool:
    return is_catalog_deep_link((start_param or "").strip() or None)


def telegram_launch_context(init_data_raw: str | None) -> dict[str, str]:
    """``chat_type`` / ``start_param`` из initData (подпись уже проверил auth-dependency)."""
    out: dict[str, str] = {}
    if not init_data_raw:
        return out
    try:
        pairs = parse_qsl(init_data_raw, keep_blank_values=False)
    except ValueError:
        return out
    for key, value in pairs:
        if key in ("chat_type", "start_param") and value:
            out[key] = value[:64]
    return out


def is_share_attributed_deeplink_open(start_param: str | None, *, chat_type: str | None) -> bool:
    """Вход в мини-апп, который засчитывается в C-B как «открыли то, чем поделились».

    * диплинк конкретного места/подборки (``arena_*``, ``catalog_<город>…``);
    * не голый ``catalog`` — это маркетинговый ``/go``, а не шер;
    * запуск из чата (``chat_type`` в подписанной initData): Telegram кладёт его только когда
      Mini App открыт прямой ссылкой из переписки. Переход с CTA публичной страницы или ``/go``
      идёт из браузера — чата нет, ``chat_type`` пуст, в C-B не попадает.
    """
    sp = (start_param or "").strip()
    if not sp or sp == CATALOG_START_ANY:
        return False
    if not is_share_deeplink_start_param(sp):
        return False
    return bool((chat_type or "").strip())


async def resolve_entry_scope(
    session: AsyncSession,
    *,
    start_param: str | None,
    city_id: int | None,
    arena_id: int | None,
) -> tuple[int | None, int | None]:
    """(city_id, arena_id) входа в мини-апп: из тела, иначе из диплинка; город — из арены.

    Неизвестные id отбрасываются (FK на arenas/cities уронил бы вставку и потерял событие).
    """
    sp = (start_param or "").strip() or None
    if arena_id is None:
        place = parse_place_deep_link(sp)
        if place is not None:
            arena_id = place[0]
    if city_id is None and arena_id is None:
        target = parse_catalog_start_param(sp)
        if target is not None and target[0] is not None:
            city_id = int(target[0])
    if arena_id is not None:
        row = (
            await session.execute(text("SELECT city_id FROM arenas WHERE id = :id"), {"id": int(arena_id)})
        ).first()
        if row is None:
            arena_id = None
        elif row[0] is not None:
            city_id = int(row[0])
    if city_id is not None:
        exists = (await session.execute(text("SELECT 1 FROM cities WHERE id = :id"), {"id": int(city_id)})).first()
        if exists is None:
            city_id = None
    return city_id, arena_id


async def record_catalog_consumer_event(
    session: AsyncSession,
    *,
    kind: str,
    surface: str,
    actor_hash: str | None = None,
    city_id: int | None = None,
    arena_id: int | None = None,
    start_param: str | None = None,
    payload: dict[str, Any] | None = None,
    dedup: bool = True,
) -> bool:
    """Append one row (or nothing on dedup conflict). Returns True if inserted. Never raises into HTTP handlers."""
    if kind not in CATALOG_CONSUMER_KINDS:
        raise ValueError(f"Unknown catalog consumer kind: {kind!r}")
    if actor_hash and actor_hash in excluded_catalog_actor_hashes():
        return False
    sp = (start_param or "").strip() or None
    if sp and not is_valid_start_param(sp):
        sp = None
    day = catalog_event_day_minsk()
    body = dict(payload or {})
    dedup_key = (
        event_dedup_hash(
            kind=kind,
            surface=surface,
            actor_hash=actor_hash,
            day=day,
            city_id=city_id,
            arena_id=arena_id,
            variant=str(body["src"]) if body.get("src") in SHARE_SRC_VALUES else None,
        )
        if dedup
        else None
    )
    try:
        result = await session.execute(
            text(
                """
                INSERT INTO catalog_consumer_events
                    (kind, surface, actor_hash, city_id, arena_id, start_param, payload, dedup_key)
                VALUES
                    (:kind, :surface, :actor, :city_id, :arena_id, :start_param, CAST(:payload AS jsonb), :dedup_key)
                ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
                RETURNING id
                """
            ),
            {
                "kind": kind,
                "surface": surface,
                "actor": actor_hash,
                "city_id": city_id,
                "arena_id": arena_id,
                "start_param": sp,
                "payload": json.dumps(body, ensure_ascii=False),
                "dedup_key": dedup_key,
            },
        )
        inserted = result.first() is not None
        await session.commit()
        return inserted
    except Exception:
        logger.exception("catalog_consumer_events insert failed kind=%s surface=%s", kind, surface)
        await session.rollback()
        return False


async def metrics_comparable_since(session: AsyncSession) -> datetime | None:
    """Начало сопоставимого ряда (UTC). История до TASK-189 не пересчитывается.

    1. ``CATALOG_METRICS_COMPARABLE_SINCE`` (ISO-дата, полночь по Минску) — ручная граница;
    2. иначе — первая строка нового формата (``dedup_key IS NOT NULL``): её пишет только код
       после выката и только при заданном секрете актёра, поэтому граница ставится сама в момент
       деплоя и не врёт, если деплой или секрет задержатся (захардкоженная дата — угадывание).
    ``None`` — строк нового формата ещё нет.
    """
    raw = (os.environ.get(COMPARABLE_SINCE_ENV) or "").strip()
    if raw:
        try:
            return minsk_day_start_utc(date.fromisoformat(raw[:10]))
        except ValueError:
            logger.warning("bad %s=%r; falling back to first dedup row", COMPARABLE_SINCE_ENV, raw)
    value = (
        await session.execute(
            text("SELECT MIN(occurred_at) FROM catalog_consumer_events WHERE dedup_key IS NOT NULL")
        )
    ).scalar()
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _as_utc(as_of: datetime | None) -> datetime:
    as_of_dt = as_of or datetime.now(timezone.utc)
    if as_of_dt.tzinfo is None:
        as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
    return as_of_dt


async def get_catalog_wau(
    session: AsyncSession,
    *,
    days: int = 7,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Уникальные ``actor_hash`` с просмотром публички или входом в мини-апп каталога.

    Окно не начинается раньше сопоставимого ряда: дневные хэши до TASK-189 раздували бы WAU.
    """
    as_of_dt = _as_utc(as_of)
    since = as_of_dt - timedelta(days=days)
    comparable = await metrics_comparable_since(session)
    if comparable is not None and comparable > since:
        since = comparable
    ex_sql, ex_params = catalog_actor_exclusion_sql()
    row = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT actor_hash) AS wau
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND actor_hash IS NOT NULL
                  AND kind IN (:pv, :mini)
                  AND COALESCE(payload->>'ua_class', 'human') = 'human'
                  {ex_sql}
                """
            ),
            {
                "since": since,
                "as_of": as_of_dt,
                "pv": KIND_PUBLIC_PAGE_VIEW,
                "mini": KIND_MINIAPP_CATALOG_ENTRY,
                **ex_params,
            },
        )
    ).first()
    wau = int(row[0] or 0) if row else 0
    return {
        "metric": "catalog_wau",
        "days": days,
        "since": since.isoformat(),
        "as_of": as_of_dt.isoformat(),
        "comparable_since": comparable.isoformat() if comparable else None,
        "unique_actors": wau,
    }


async def record_public_contact_click(
    session: AsyncSession,
    request: Any,
    *,
    action: str,
    surface: str,
    city_id: int | None = None,
    arena_id: int | None = None,
) -> None:
    """Клик «позвонить / билеты / маршрут» с SSR — demand-событие TASK-189."""
    from starlette.requests import Request

    if not isinstance(request, Request):
        return
    from src.api.middleware.http_limits import client_ip_from_request

    act = (action or "").strip().lower()
    if act not in ("phone", "tickets", "direction"):
        return
    user_agent = request.headers.get("user-agent")
    actor = public_actor_hash(client_ip=client_ip_from_request(request), user_agent=user_agent)
    await record_catalog_consumer_event(
        session,
        kind=KIND_PUBLIC_CONTACT_CLICK,
        surface=(surface or "place_page").strip().lower()[:40],
        actor_hash=actor,
        city_id=city_id,
        arena_id=arena_id,
        payload={"action": act, "ua_class": classify_user_agent(user_agent)},
    )


def public_page_view_attribution_payload(extra_payload: dict[str, Any] | None) -> dict[str, str]:
    """Допустимые ключи шаринга в ``public_page_view``: ``s``, ``i``, ``src``."""
    if not extra_payload:
        return {}
    out: dict[str, str] = {}
    for key, value in extra_payload.items():
        if key not in _PUBLIC_PAGE_VIEW_EXTRA_KEYS or value is None:
            continue
        if key == "src":
            raw = str(value).strip().lower()
            if raw not in SHARE_SRC_VALUES:
                continue
            out["src"] = raw
        elif key == "s":
            s = str(value).strip()
            if s.isdigit() and 0 < int(s) < 2**31:
                out["s"] = s
        elif key == "i":
            if str(value).strip().lower() in ("1", "true", "yes"):
                out["i"] = "1"
    return out


def format_share_attribution_report_lines(cb: Mapping[str, Any]) -> list[str]:
    """Строки отчёта по каналам шаринга (чистая форматировка, без БД)."""
    lines: list[str] = []
    by_src = cb.get("public_page_view_by_src") or {}
    if by_src:
        lines.append("  Просмотры публички с src:")
        for key in SHARE_SRC_VALUES:
            if int(by_src.get(key) or 0):
                lines.append(f"    {key}: {by_src[key]}")
    with_s = int(cb.get("public_page_view_with_session") or 0)
    if with_s:
        lines.append(f"  Просмотры с ?s= в payload: {with_s}")
    cta_by_src = cb.get("public_telegram_cta_clicks_by_src") or {}
    if cta_by_src:
        lines.append("  Клики CTA «Telegram» с src:")
        for key in SHARE_SRC_VALUES:
            if int(cta_by_src.get(key) or 0):
                lines.append(f"    {key}: {cta_by_src[key]}")
    return lines


async def record_public_page_view(
    session: AsyncSession,
    request: Any,
    *,
    surface: str,
    city_id: int | None,
    arena_id: int | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    """GET /p/, /c/, ice today — один просмотр на actor × арена в сутки (Минск)."""
    from starlette.requests import Request

    if not isinstance(request, Request):
        return
    from src.api.middleware.http_limits import client_ip_from_request

    user_agent = request.headers.get("user-agent")
    actor = public_actor_hash(client_ip=client_ip_from_request(request), user_agent=user_agent)
    body: dict[str, Any] = {"path": str(request.url.path), "ua_class": classify_user_agent(user_agent)}
    body.update(public_page_view_attribution_payload(extra_payload))
    await record_catalog_consumer_event(
        session,
        kind=KIND_PUBLIC_PAGE_VIEW,
        surface=surface,
        actor_hash=actor,
        city_id=city_id,
        arena_id=arena_id,
        payload=body,
    )


async def get_catalog_weekly_unique_by_city(
    session: AsyncSession,
    *,
    weeks: int = 4,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Недели (пн, Минск) × город: уникальные актёры с demand-событием и число событий.

    Только сопоставимый ряд; пока его нет — пустой список.
    """
    as_of_dt = _as_utc(as_of)
    comparable = await metrics_comparable_since(session)
    if comparable is None:
        return []
    since = max(as_of_dt - timedelta(weeks=weeks), comparable)
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    rows = (
        await session.execute(
            text(
                f"""
                SELECT (date_trunc('week', e.occurred_at AT TIME ZONE 'Europe/Minsk'))::date AS week_start,
                       e.city_id,
                       c.name AS city_name,
                       COUNT(DISTINCT e.actor_hash) AS unique_actors,
                       COUNT(*) AS events
                FROM catalog_consumer_events e
                LEFT JOIN cities c ON c.id = e.city_id
                WHERE e.occurred_at >= :since AND e.occurred_at < :as_of
                  AND e.actor_hash IS NOT NULL
                  AND e.kind IN (:pv, :mini)
                  AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
                  {ex_sql}
                GROUP BY 1, 2, 3
                ORDER BY 1 DESC, 4 DESC
                """
            ),
            {
                "since": since,
                "as_of": as_of_dt,
                "pv": KIND_PUBLIC_PAGE_VIEW,
                "mini": KIND_MINIAPP_CATALOG_ENTRY,
                **ex_params,
            },
        )
    ).mappings().all()
    return [
        {
            "week_start": row["week_start"].isoformat() if row["week_start"] else None,
            "city_id": row["city_id"],
            "city_name": row["city_name"],
            "unique_actors": int(row["unique_actors"] or 0),
            "events": int(row["events"] or 0),
        }
        for row in rows
    ]


async def get_catalog_top_arenas_by_events(
    session: AsyncSession,
    *,
    days: int = 7,
    as_of: datetime | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Demand-события по арене за окно (только сопоставимый ряд)."""
    as_of_dt = _as_utc(as_of)
    comparable = await metrics_comparable_since(session)
    if comparable is None:
        return []
    since = max(as_of_dt - timedelta(days=days), comparable)
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    rows = (
        await session.execute(
            text(
                f"""
                SELECT e.arena_id,
                       a.name AS arena_name,
                       e.city_id,
                       COUNT(*) AS events,
                       COUNT(DISTINCT e.actor_hash) AS unique_actors
                FROM catalog_consumer_events e
                LEFT JOIN arenas a ON a.id = e.arena_id
                WHERE e.occurred_at >= :since AND e.occurred_at < :as_of
                  AND e.arena_id IS NOT NULL
                  AND e.kind IN (:pv, :mini)
                  AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
                  {ex_sql}
                GROUP BY e.arena_id, a.name, e.city_id
                ORDER BY events DESC, e.arena_id
                LIMIT :lim
                """
            ),
            {
                "since": since,
                "as_of": as_of_dt,
                "pv": KIND_PUBLIC_PAGE_VIEW,
                "mini": KIND_MINIAPP_CATALOG_ENTRY,
                "lim": limit,
                **ex_params,
            },
        )
    ).mappings().all()
    return [
        {
            "arena_id": row["arena_id"],
            "arena_name": row["arena_name"],
            "city_id": row["city_id"],
            "events": int(row["events"] or 0),
            "unique_actors": int(row["unique_actors"] or 0),
        }
        for row in rows
    ]


async def get_catalog_virality_cb_metrics(
    session: AsyncSession,
    *,
    days: int = 7,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """
    C-B прокси: shares/WAU и share→open — входы в мини-апп, помеченные при записи
    :func:`is_share_attributed_deeplink_open` (``payload.share_deeplink``).
    """
    as_of_dt = _as_utc(as_of)
    since = as_of_dt - timedelta(days=days)
    share_ex_sql, share_ex_params = share_actor_exclusion_sql(since=since, until=as_of_dt)
    open_ex_sql, open_ex_params = catalog_actor_exclusion_sql()

    shares = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(*) AS events,
                       COUNT(DISTINCT actor_hash) AS sharers
                FROM client_share_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind IN ('place', 'selection', 'ice_city_day')
                  {share_ex_sql}
                """
            ),
            {"since": since, "as_of": as_of_dt, **share_ex_params},
        )
    ).first()

    deeplink_opens = (
        await session.execute(
            text(
                f"""
                SELECT COUNT(*) AS events,
                       COUNT(DISTINCT actor_hash) AS actors
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :kind
                  AND COALESCE((payload->>'share_deeplink')::boolean, false)
                  {open_ex_sql}
                """
            ),
            {
                "since": since,
                "as_of": as_of_dt,
                "kind": KIND_MINIAPP_CATALOG_ENTRY,
                **open_ex_params,
            },
        )
    ).first()

    cta_clicks = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :kind
                  AND COALESCE(payload->>'ua_class', 'human') = 'human'
                """
            ),
            {"since": since, "as_of": as_of_dt, "kind": KIND_PUBLIC_TELEGRAM_CTA},
        )
    ).scalar_one()

    page_view_by_src_rows = (
        await session.execute(
            text(
                """
                SELECT payload->>'src' AS src, COUNT(*) AS n
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :pv
                  AND payload->>'src' IS NOT NULL
                  AND payload->>'src' != ''
                GROUP BY payload->>'src'
                """
            ),
            {"since": since, "as_of": as_of_dt, "pv": KIND_PUBLIC_PAGE_VIEW},
        )
    ).mappings().all()
    page_view_with_session = (
        await session.execute(
            text(
                """
                SELECT COUNT(*) FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :pv
                  AND payload->>'s' IS NOT NULL
                  AND payload->>'s' != ''
                """
            ),
            {"since": since, "as_of": as_of_dt, "pv": KIND_PUBLIC_PAGE_VIEW},
        )
    ).scalar_one()
    cta_by_src_rows = (
        await session.execute(
            text(
                """
                SELECT payload->>'src' AS src, COUNT(*) AS n
                FROM catalog_consumer_events
                WHERE occurred_at >= :since AND occurred_at < :as_of
                  AND kind = :cta
                  AND COALESCE(payload->>'ua_class', 'human') = 'human'
                  AND payload->>'src' IS NOT NULL
                  AND payload->>'src' != ''
                GROUP BY payload->>'src'
                """
            ),
            {"since": since, "as_of": as_of_dt, "cta": KIND_PUBLIC_TELEGRAM_CTA},
        )
    ).mappings().all()

    wau = await get_catalog_wau(session, days=days, as_of=as_of_dt)
    share_events = int(shares[0] or 0) if shares else 0
    sharers = int(shares[1] or 0) if shares else 0
    open_events = int(deeplink_opens[0] or 0) if deeplink_opens else 0
    wau_n = int(wau["unique_actors"] or 0)

    return {
        "metric": "catalog_virality_cb",
        "days": days,
        "since": since.isoformat(),
        "as_of": as_of_dt.isoformat(),
        "share_events": share_events,
        "distinct_sharers": sharers,
        "catalog_wau": wau_n,
        "shares_per_wau": round(share_events / wau_n, 4) if wau_n else None,
        "public_telegram_cta_clicks": int(cta_clicks or 0),
        "miniapp_deeplink_entries": open_events,
        "share_to_deeplink_open_pct": round(100.0 * open_events / share_events, 1) if share_events else None,
        "public_page_view_by_src": {str(r["src"]): int(r["n"] or 0) for r in page_view_by_src_rows},
        "public_page_view_with_session": int(page_view_with_session or 0),
        "public_telegram_cta_clicks_by_src": {str(r["src"]): int(r["n"] or 0) for r in cta_by_src_rows},
    }


def _pulse_calendar(as_of_dt: datetime) -> dict[str, Any]:
    """Границы текущей и прошлой недели (пн, Минск) и календарного месяца."""
    day = catalog_event_day_minsk(as_of_dt)
    week_start = day - timedelta(days=day.weekday())
    prev_start = week_start - timedelta(days=7)
    month_start = day.replace(day=1)
    return {
        "week_start": minsk_day_start_utc(week_start),
        "prev_week_start": minsk_day_start_utc(prev_start),
        "month_start": minsk_day_start_utc(month_start),
        "week_start_date": week_start,
        "prev_week_start_date": prev_start,
        "month_start_date": month_start,
        "month_label": _RU_MONTHS[month_start.month],
    }


async def get_catalog_demand_pulse(
    session: AsyncSession,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Пульс спроса для админского «Сейчас».

    Главное число — разные Telegram-аккаунты Минска за календарную неделю (пн–вс, Минск)
    и за прошлую. Месяц — те же аккаунты с 1-го числа, рядом с порогом 300.
    Остальные города — только где на этой неделе есть хотя бы один аккаунт.
    «Уже были» — пересечение минских аккаунтов этой и прошлой недели.

    «Поделиться» — разные аккаунты, не нажатия. «Открыли» — разные аккаунты, открывшие
    ссылку из чата. Процент есть только когда открытий не меньше десяти.
    Арены — только входы в мини-приложение, с городом. Сайт — отдельная строка браузеров.

    Служебные Telegram-аккаунты не входят, в том числе в уже записанные строки.
    Их заходы на сайт остаются в строке браузеров.
    """
    as_of_dt = _as_utc(as_of)
    cal = _pulse_calendar(as_of_dt)
    comparable = await metrics_comparable_since(session)
    week_start = cal["week_start"]
    prev_start = cal["prev_week_start"]
    month_start = cal["month_start"]
    range_start = min(prev_start, month_start)
    ex_sql, ex_params = catalog_actor_exclusion_sql("e.actor_hash")
    human = "COALESCE(e.payload->>'ua_class', 'human') = 'human'"
    comparable_sql = " AND e.occurred_at >= :comparable" if comparable is not None else ""
    base = {
        "as_of": as_of_dt,
        "week": week_start,
        "prev": prev_start,
        "month": month_start,
        "range_start": range_start,
        "mini": KIND_MINIAPP_CATALOG_ENTRY,
        "pv": KIND_PUBLIC_PAGE_VIEW,
        **({"comparable": comparable} if comparable is not None else {}),
        **ex_params,
    }

    minsk_row = (
        await session.execute(
            text("SELECT id, name FROM cities WHERE lower(name) = 'минск' AND country = 'BY' ORDER BY id LIMIT 1")
        )
    ).first()
    minsk_id = int(minsk_row[0]) if minsk_row else None
    minsk_name = str(minsk_row[1]) if minsk_row else "Минск"

    this_week = prev_week = month_n = returning = 0
    other_cities: list[dict[str, Any]] = []
    browsers = 0
    top_arenas: list[dict[str, Any]] = []
    if comparable is not None:
        city_rows = (
            await session.execute(
                text(
                    f"""
                    SELECT e.city_id,
                           c.name AS city_name,
                           COUNT(DISTINCT e.actor_hash) FILTER (
                               WHERE e.occurred_at >= :week
                           ) AS this_week,
                           COUNT(DISTINCT e.actor_hash) FILTER (
                               WHERE e.occurred_at >= :prev AND e.occurred_at < :week
                           ) AS prev_week,
                           COUNT(DISTINCT e.actor_hash) FILTER (
                               WHERE e.occurred_at >= :month
                           ) AS month_n
                    FROM catalog_consumer_events e
                    JOIN cities c ON c.id = e.city_id
                    WHERE e.occurred_at >= :range_start AND e.occurred_at < :as_of
                      AND e.actor_hash IS NOT NULL
                      AND e.kind = :mini
                      AND {human}
                      {comparable_sql}
                      {ex_sql}
                    GROUP BY e.city_id, c.name
                    """
                ),
                base,
            )
        ).mappings().all()
        for row in city_rows:
            item = {
                "city_id": int(row["city_id"]),
                "city_name": row["city_name"],
                "telegram_this_week": int(row["this_week"] or 0),
                "telegram_prev_week": int(row["prev_week"] or 0),
                "telegram_month": int(row["month_n"] or 0),
            }
            if minsk_id is not None and item["city_id"] == minsk_id:
                this_week = item["telegram_this_week"]
                prev_week = item["telegram_prev_week"]
                month_n = item["telegram_month"]
            elif item["telegram_this_week"] > 0:
                other_cities.append(item)
        other_cities.sort(key=lambda c: (-c["telegram_this_week"], c["city_name"] or ""))

        if minsk_id is not None:
            returning = int(
                (
                    await session.execute(
                        text(
                            f"""
                            SELECT COUNT(*) FROM (
                                SELECT e.actor_hash
                                FROM catalog_consumer_events e
                                WHERE e.occurred_at >= :week AND e.occurred_at < :as_of
                                  AND e.city_id = :minsk
                                  AND e.actor_hash IS NOT NULL
                                  AND e.kind = :mini
                                  AND {human}
                                  {comparable_sql}
                                  {ex_sql}
                                INTERSECT
                                SELECT e.actor_hash
                                FROM catalog_consumer_events e
                                WHERE e.occurred_at >= :prev AND e.occurred_at < :week
                                  AND e.city_id = :minsk
                                  AND e.actor_hash IS NOT NULL
                                  AND e.kind = :mini
                                  AND {human}
                                  {comparable_sql}
                                  {ex_sql}
                            ) returning_actors
                            """
                        ),
                        {**base, "minsk": minsk_id},
                    )
                ).scalar_one()
                or 0
            )

        browsers = int(
            (
                await session.execute(
                    text(
                        f"""
                        SELECT COUNT(DISTINCT e.actor_hash)
                        FROM catalog_consumer_events e
                        WHERE e.occurred_at >= :week AND e.occurred_at < :as_of
                          AND e.actor_hash IS NOT NULL
                          AND e.kind = :pv
                          AND {human}
                          {comparable_sql}
                        """
                    ),
                    base,
                )
            ).scalar_one()
            or 0
        )
        arena_rows = (
            await session.execute(
                text(
                    f"""
                    SELECT e.arena_id,
                           a.name AS arena_name,
                           c.name AS city_name,
                           COUNT(DISTINCT e.actor_hash) AS unique_actors
                    FROM catalog_consumer_events e
                    LEFT JOIN arenas a ON a.id = e.arena_id
                    LEFT JOIN cities c ON c.id = e.city_id
                    WHERE e.occurred_at >= :week AND e.occurred_at < :as_of
                      AND e.arena_id IS NOT NULL
                      AND e.actor_hash IS NOT NULL
                      AND e.kind = :mini
                      AND {human}
                      {comparable_sql}
                      {ex_sql}
                    GROUP BY e.arena_id, a.name, c.name
                    ORDER BY unique_actors DESC, e.arena_id
                    LIMIT 5
                    """
                ),
                base,
            )
        ).mappings().all()
        top_arenas = [
            {
                "arena_id": row["arena_id"],
                "arena_name": row["arena_name"],
                "city_name": row["city_name"],
                "unique_actors": int(row["unique_actors"] or 0),
            }
            for row in arena_rows
        ]

    tickets = 0
    share_people = 0
    share_opens = 0
    if comparable is not None:
        tickets = int(
            (
                await session.execute(
                    text(
                        f"""
                        SELECT COUNT(DISTINCT e.actor_hash)
                        FROM catalog_consumer_events e
                        WHERE e.occurred_at >= :week AND e.occurred_at < :as_of
                          AND e.actor_hash IS NOT NULL
                          AND e.kind = :tickets
                          AND e.payload->>'action' = 'tickets'
                          AND {human}
                          {comparable_sql}
                        """
                    ),
                    {**base, "tickets": KIND_PUBLIC_CONTACT_CLICK},
                )
            ).scalar_one()
            or 0
        )
        share_ex_sql, share_ex_params = share_actor_exclusion_sql(since=week_start, until=as_of_dt)
        share_people = int(
            (
                await session.execute(
                    text(
                        f"""
                        SELECT COUNT(DISTINCT actor_hash)
                        FROM client_share_events
                        WHERE occurred_at >= :since AND occurred_at < :as_of
                          AND kind IN ('place', 'selection', 'ice_city_day')
                          AND actor_hash IS NOT NULL
                          {share_ex_sql}
                        """
                    ),
                    {"since": week_start, "as_of": as_of_dt, **share_ex_params},
                )
            ).scalar_one()
            or 0
        )
        open_ex_sql, open_ex_params = catalog_actor_exclusion_sql()
        share_opens = int(
            (
                await session.execute(
                    text(
                        f"""
                        SELECT COUNT(DISTINCT actor_hash)
                        FROM catalog_consumer_events
                        WHERE occurred_at >= :since AND occurred_at < :as_of
                          AND kind = :kind
                          AND actor_hash IS NOT NULL
                          AND dedup_key IS NOT NULL
                          AND COALESCE((payload->>'share_deeplink')::boolean, false)
                          {comparable_sql.replace("e.", "")}
                          {open_ex_sql}
                        """
                    ),
                    {
                        "since": week_start,
                        "as_of": as_of_dt,
                        "kind": KIND_MINIAPP_CATALOG_ENTRY,
                        **({"comparable": comparable} if comparable is not None else {}),
                        **open_ex_params,
                    },
                )
            ).scalar_one()
            or 0
        )

    remaining = max(0, MINSK_MONTHLY_TELEGRAM_GOAL - month_n)
    return {
        "metric": "catalog_demand_pulse",
        "as_of": as_of_dt.isoformat(),
        "comparable_since": comparable.isoformat() if comparable else None,
        "comparable_since_date": (
            comparable.astimezone(ZoneInfo(NOTIFICATION_TZ)).date().isoformat() if comparable else None
        ),
        "week_start": cal["week_start_date"].isoformat(),
        "prev_week_start": cal["prev_week_start_date"].isoformat(),
        "month_start": cal["month_start_date"].isoformat(),
        "month_label": cal["month_label"],
        "minsk_name": minsk_name,
        "minsk_telegram_this_week": this_week,
        "minsk_telegram_prev_week": prev_week,
        "minsk_telegram_month": month_n,
        "minsk_month_goal": MINSK_MONTHLY_TELEGRAM_GOAL,
        "minsk_month_remaining": remaining,
        "minsk_returning": returning,
        "cities": [
            {
                "city_name": c["city_name"],
                "telegram_this_week": c["telegram_this_week"],
                "telegram_prev_week": c["telegram_prev_week"],
            }
            for c in other_cities
        ],
        "browsers_this_week": browsers,
        "tickets_intent_actors_7d": tickets,
        "share_people_7d": share_people,
        "share_open_7d": share_opens,
        "share_open_pct": (
            round(100.0 * share_opens / share_people, 1) if share_people and share_opens >= 10 else None
        ),
        "top_arenas_7d": top_arenas,
    }


async def purge_old_catalog_consumer_events(
    session: AsyncSession,
    *,
    now: datetime,
    keep_days: int = CATALOG_CONSUMER_EVENTS_RETENTION_DAYS,
) -> int:
    """Удаляет события старше ``keep_days`` (400 дней: год неделя-к-неделе + запас)."""
    result = await session.execute(
        text("DELETE FROM catalog_consumer_events WHERE occurred_at < :cutoff"),
        {"cutoff": now - timedelta(days=keep_days)},
    )
    return int(result.rowcount or 0)
