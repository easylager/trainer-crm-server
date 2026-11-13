"""События базовой линии карточки тренера (TASK-397, SPEC §13).

Пишутся в ``trainer_demand_events``: у ``kind`` нет CHECK в базе, новая таблица не нужна.
Колонка ``source`` остаётся пустой — туда Lead Mode кладёт свои коды, и смешивать их
с ``via`` нельзя. Метка источника лежит в ``payload``.

В payload нет телефона, имени и ``init_data``. Словарь собирается по белому списку,
чужие ключи не копируются.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_source import BOOKING_SOURCES, BookingSource
from src.application.demand_signals_use_cases import compute_dedup_hash
from src.infrastructure.db.models import (
    DEMAND_EVENT_BOOKING_CONFIRMED,
    DEMAND_EVENT_BOOKING_FORM_OPEN,
    DEMAND_EVENT_BOOKING_SUBMIT,
    DEMAND_EVENT_CARD_CTA_TAP,
    DEMAND_EVENT_LINK_REG_FIRST_TAP,
    DEMAND_EVENT_TRAINER_CARD_VIEW,
)
from src.infrastructure.repositories.demand_signals_repository import DemandSignalsRepository
from src.shared.ua_class import UA_CLASSES, classify_user_agent

logger = logging.getLogger(__name__)

MEASURE_KINDS = (
    DEMAND_EVENT_TRAINER_CARD_VIEW,
    DEMAND_EVENT_CARD_CTA_TAP,
    DEMAND_EVENT_BOOKING_FORM_OPEN,
    DEMAND_EVENT_BOOKING_SUBMIT,
    DEMAND_EVENT_BOOKING_CONFIRMED,
    DEMAND_EVENT_LINK_REG_FIRST_TAP,
)
_MEASURE_KIND_SET = frozenset(MEASURE_KINDS)

#: Клиент Mini App может прислать только эти. Отправку и подтверждение пишет сервер.
CLIENT_MEASURE_KINDS = frozenset(
    {
        DEMAND_EVENT_TRAINER_CARD_VIEW,
        DEMAND_EVENT_CARD_CTA_TAP,
        DEMAND_EVENT_BOOKING_FORM_OPEN,
        DEMAND_EVENT_LINK_REG_FIRST_TAP,
    }
)

CTA_ACTIONS = frozenset({"slot", "book", "write", "call", "request"})
FIRST_TAP_TARGETS = frozenset({"hub", "card", "slot"})
SURFACES = frozenset({"site", "miniapp"})
_BOOKING_SOURCE_SET = frozenset(BOOKING_SOURCES)
_VIA_RE = re.compile(r"^([pck])([1-9][0-9]{0,8})$")
_UA_SET = frozenset(UA_CLASSES)

# Срез читает и скрипт, и тесты — одна строка SQL.
WEEKLY_SITE_VIEWS_SQL = """
SELECT (date_trunc('week', e.occurred_at AT TIME ZONE 'Europe/Minsk'))::date AS week_start,
       COALESCE(NULLIF(e.payload->>'via', ''), 'none') AS via,
       COUNT(*)::int AS views
FROM trainer_demand_events e
WHERE e.kind = 'trainer_card_view'
  AND e.payload->>'surface' = 'site'
  AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
  AND e.occurred_at >= :since AND e.occurred_at < :until
GROUP BY 1, 2
ORDER BY 1, 2
"""

CTA_TAPS_SQL = """
SELECT COALESCE(e.payload->>'surface', '') AS surface,
       COALESCE(e.payload->>'action', '') AS action,
       COUNT(*)::int AS taps
FROM trainer_demand_events e
WHERE e.kind = 'card_cta_tap'
  AND e.occurred_at >= :since AND e.occurred_at < :until
  AND (
        e.payload->>'surface' = 'miniapp'
        OR COALESCE(e.payload->>'ua_class', 'human') = 'human'
      )
GROUP BY 1, 2
ORDER BY 1, 2
"""

FUNNEL_EVENTS_SQL = """
SELECT e.kind, COUNT(*)::int AS n
FROM trainer_demand_events e
WHERE e.kind IN ('booking_form_open', 'booking_submit', 'booking_confirmed')
  AND e.occurred_at >= :since AND e.occurred_at < :until
GROUP BY 1
ORDER BY 1
"""

CONFIRM_LATENCY_SQL = """
SELECT COUNT(*)::int AS n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY secs) AS p50_seconds,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY secs) AS p90_seconds
FROM (
    SELECT EXTRACT(EPOCH FROM (e.occurred_at - b.created_at)) AS secs
    FROM trainer_demand_events e
    JOIN bookings b ON b.id = (e.payload->>'booking_id')::bigint
    WHERE e.kind = 'booking_confirmed'
      AND e.payload->>'booking_id' ~ '^[0-9]+$'
      AND e.occurred_at >= :since AND e.occurred_at < :until
      AND NOT b.is_sandbox
) s
WHERE secs >= 0
"""

SELF_BOOKING_FUNNEL_SQL = """
SELECT COUNT(*) FILTER (WHERE b.source IS NOT NULL)::int AS submitted,
       COUNT(*) FILTER (
           WHERE b.source IS NOT NULL AND b.status IN ('confirmed', 'completed')
       )::int AS confirmed
FROM bookings b
WHERE NOT b.is_sandbox
  AND b.created_at >= :since AND b.created_at < :until
"""

FIRST_CONFIRMED_TRAINERS_SQL = """
SELECT COUNT(*)::int AS trainers
FROM (
    SELECT b.trainer_id, MIN(b.created_at) AS first_at
    FROM bookings b
    WHERE NOT b.is_sandbox
      AND b.status IN ('confirmed', 'completed')
    GROUP BY b.trainer_id
) s
WHERE s.first_at >= :since AND s.first_at < :until
"""

FIRST_TAP_SQL = """
SELECT COALESCE(e.payload->>'target', '') AS target, COUNT(*)::int AS n
FROM trainer_demand_events e
WHERE e.kind = 'link_reg_first_tap'
  AND e.occurred_at >= :since AND e.occurred_at < :until
GROUP BY 1
ORDER BY 1
"""

SITE_WRITE_CLICKS_SQL = """
SELECT COUNT(*)::int AS writes
FROM catalog_consumer_events e
WHERE e.kind = 'public_contact_click'
  AND e.payload->>'action' = 'telegram'
  AND COALESCE(e.payload->>'ua_class', 'human') = 'human'
  AND e.occurred_at >= :since AND e.occurred_at < :until
"""


def clean_via_token(raw: str | None) -> str | None:
    """``link`` / ``share`` / ``p3`` / ``k1`` / ``c12``. Всё остальное — не метка."""
    token = (raw or "").strip().lower()
    if token in ("link", "share"):
        return token
    match = _VIA_RE.match(token)
    if match is None:
        return None
    return f"{match.group(1)}{int(match.group(2))}"


def via_from_start_param(start_param: str | None) -> str | None:
    """Метка из подписанного ``start_param``. Старая ``trainer_7_a_3`` — каток ``p3``."""
    from src.application.place_links import parse_trainer_start_param

    parsed = parse_trainer_start_param(start_param) if (start_param or "").strip() else None
    if not parsed:
        return None
    if parsed.get("via"):
        return clean_via_token(str(parsed["via"]))
    arena_id = parsed.get("arena_id")
    if arena_id:
        return clean_via_token(f"p{int(arena_id)}")
    return None


def via_from_booking_source(source: BookingSource | None) -> str | None:
    """Обратно к метке ``via``, если у кода записи она была."""
    if source is None:
        return None
    if source.code == "link":
        return "link"
    if source.code == "share":
        return "share"
    if source.code == "site_place" and source.arena_id:
        return clean_via_token(f"p{int(source.arena_id)}")
    if source.code == "site_city" and source.city_id:
        return clean_via_token(f"c{int(source.city_id)}")
    if source.code == "site_catalog" and source.city_id:
        return clean_via_token(f"k{int(source.city_id)}")
    return None


def measure_payload(
    *,
    surface: str | None = None,
    via: str | None = None,
    action: str | None = None,
    target: str | None = None,
    booking_id: int | None = None,
    ua_class: str | None = None,
    start_param: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Белый список полей. Телефон, имя и init_data сюда не передаются и не читаются."""
    out: dict[str, Any] = {}
    if surface in SURFACES:
        out["surface"] = surface
    token = clean_via_token(via)
    if token:
        out["via"] = token
    if action in CTA_ACTIONS:
        out["action"] = action
    if target in FIRST_TAP_TARGETS:
        out["target"] = target
    if booking_id is not None and 0 < int(booking_id) < 2**31:
        out["booking_id"] = int(booking_id)
    if ua_class in _UA_SET:
        out["ua_class"] = ua_class
    sp = (start_param or "").strip()
    if sp:
        from src.application.place_links import is_valid_start_param

        if is_valid_start_param(sp):
            out["start_param"] = sp[:64]
    code = (source or "").strip().lower()
    if code in _BOOKING_SOURCE_SET:
        out["source"] = code
    return out


def _day_dedup(*parts: str) -> str:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = "|".join((*parts, day))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def record_trainer_card_event(
    session: AsyncSession,
    *,
    trainer_id: int,
    kind: str,
    payload: dict[str, Any],
    dedup_hash: str | None = None,
) -> bool:
    """Одна строка и commit. Нет тренера или сбой — False, чужую транзакцию не откатываем,
    если commit ещё не начат: при ошибке вставки откатывается только эта попытка.
    """
    if kind not in _MEASURE_KIND_SET:
        return False
    try:
        tid = int(trainer_id)
    except (TypeError, ValueError):
        return False
    if not 0 < tid < 2**31:
        return False
    body = measure_payload(
        surface=payload.get("surface") if isinstance(payload.get("surface"), str) else None,
        via=payload.get("via") if isinstance(payload.get("via"), str) else None,
        action=payload.get("action") if isinstance(payload.get("action"), str) else None,
        target=payload.get("target") if isinstance(payload.get("target"), str) else None,
        booking_id=payload.get("booking_id") if isinstance(payload.get("booking_id"), int) else None,
        ua_class=payload.get("ua_class") if isinstance(payload.get("ua_class"), str) else None,
        start_param=payload.get("start_param") if isinstance(payload.get("start_param"), str) else None,
        source=payload.get("source") if isinstance(payload.get("source"), str) else None,
    )
    inserted = False
    found = False
    try:
        # Savepoint: сбой вставки не откатывает подтверждение записи, которое уже сделано.
        async with session.begin_nested():
            found = (
                await session.execute(text("SELECT 1 FROM trainers WHERE id = :id"), {"id": tid})
            ).first() is not None
            if found:
                inserted = await DemandSignalsRepository(session).insert_event(
                    trainer_id=tid,
                    kind=kind,
                    source=None,
                    dedup_hash=dedup_hash,
                    payload=body,
                )
        if found:
            await session.commit()
        return inserted
    except Exception:
        logger.warning(
            "trainer card measure skipped kind=%s trainer_id=%s",
            kind,
            tid,
            exc_info=True,
        )
        return False


async def record_site_trainer_card_view(
    session: AsyncSession,
    *,
    trainer_id: int,
    via: str | None,
    user_agent: str | None,
    client_ip: str | None,
) -> bool:
    """Просмотр ``/t/<id>``. Один человек — один просмотр тренера за сутки."""
    klass = classify_user_agent(user_agent)
    return await record_trainer_card_event(
        session,
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_TRAINER_CARD_VIEW,
        payload=measure_payload(surface="site", via=via, ua_class=klass),
        dedup_hash=compute_dedup_hash(
            client_ip=client_ip, user_agent=user_agent, trainer_id=int(trainer_id)
        ),
    )


async def record_miniapp_trainer_event(
    session: AsyncSession,
    *,
    trainer_id: int,
    kind: str,
    actor_hash: str | None,
    via: str | None = None,
    action: str | None = None,
    target: str | None = None,
    start_param: str | None = None,
) -> bool:
    """Событие Mini App. Просмотр карточки и открытие формы — не чаще раза в сутки на человека."""
    if kind not in CLIENT_MEASURE_KINDS:
        return False
    dedup = None
    if kind in (DEMAND_EVENT_TRAINER_CARD_VIEW, DEMAND_EVENT_BOOKING_FORM_OPEN) and actor_hash:
        dedup = _day_dedup(actor_hash, str(int(trainer_id)), kind)
    if kind == DEMAND_EVENT_LINK_REG_FIRST_TAP and actor_hash:
        # Одно первое касание на человека и тренера, не на каждые сутки.
        dedup = hashlib.sha256(f"first|{actor_hash}|{int(trainer_id)}".encode()).hexdigest()
    return await record_trainer_card_event(
        session,
        trainer_id=trainer_id,
        kind=kind,
        payload=measure_payload(
            surface="miniapp",
            via=via,
            action=action,
            target=target,
            start_param=start_param,
        ),
        dedup_hash=dedup,
    )


async def record_booking_submit(
    session: AsyncSession,
    *,
    trainer_id: int,
    booking_id: int,
    source: BookingSource | None,
) -> bool:
    code = source.code if source is not None else None
    dedup = hashlib.sha256(f"submit|{int(booking_id)}".encode()).hexdigest()
    return await record_trainer_card_event(
        session,
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_BOOKING_SUBMIT,
        payload=measure_payload(
            surface="miniapp",
            via=via_from_booking_source(source),
            booking_id=booking_id,
            source=code,
        ),
        dedup_hash=dedup,
    )


async def record_booking_confirmed(
    session: AsyncSession,
    *,
    trainer_id: int,
    booking_id: int,
) -> bool:
    dedup = hashlib.sha256(f"confirmed|{int(booking_id)}".encode()).hexdigest()
    return await record_trainer_card_event(
        session,
        trainer_id=trainer_id,
        kind=DEMAND_EVENT_BOOKING_CONFIRMED,
        payload=measure_payload(booking_id=booking_id),
        dedup_hash=dedup,
    )


def window_bounds(*, days: int, as_of: datetime | None = None) -> tuple[datetime, datetime]:
    until = as_of or datetime.now(timezone.utc)
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    return until - timedelta(days=days), until
