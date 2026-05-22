"""
Platform audit log: append-only timeline for admin «История».

Existing ``audit_log()`` calls are dual-written here when an asyncio loop is running.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db import async_session_factory

logger = logging.getLogger(__name__)

# Human-readable labels for admin UI (extend as new event types appear).
EVENT_LABELS_RU: dict[str, str] = {
    "booking.created": "Клиент создал запись",
    "booking.cancelled": "Тренер отменил запись",
    "booking.no_show": "Отметка неявки",
    "booking.problem_reported": "Тренер сообщил о проблеме на занятии",
    "client_request.created": "Клиент оставил заявку",
    "request_response.created": "Тренер откликнулся на заявку",
    "request.trainer_booked_client": "Тренер записал клиента по заявке",
    "trainer.created": "Создан аккаунт тренера",
    "trainer.linked": "Тренер привязал Telegram",
    "trainer.profile_updated": "Тренер обновил профиль",
    "trainer.status_updated": "Изменён статус тренера",
    "trainer.approved": "Админ одобрил тренера",
    "trainer.needs_edit": "Админ запросил правки профиля",
    "trainer.review": "Тренер оставил отзыв",
    "trainer.education_created": "Добавлено образование тренера",
    "trainer.education_updated": "Обновлено образование тренера",
    "trainer.education_deleted": "Удалено образование тренера",
    "trainer.moderation_submitted": "Профиль отправлен на модерацию",
    "trainer.invite_link_copied": "Тренер скопировал ссылку для клиентов",
    "schedule.week_slots_updated": "Тренер изменил слоты недели",
    "schedule.week_applied": "Тренер применил шаблон расписания",
    "slot.deleted": "Тренер удалил слот",
    "legal.trainer_terms_created": "Опубликованы условия для тренеров",
    "legal.trainer_terms_accepted": "Тренер принял условия",
    "referral.admin_adjust": "Админ изменил реферальный баланс",
    "support.replied": "Админ ответил в поддержку",
    "subscription.invoice_paid": "Оплачен счёт подписки",
}

ACTOR_LABELS_RU: dict[str, str] = {
    "client_bot": "Клиент",
    "trainer_bot": "Тренер",
    "admin_bot": "Админ",
    "api": "API",
}


def event_label_ru(event_type: str) -> str:
    return EVENT_LABELS_RU.get(event_type, event_type.replace(".", " · "))


def _json_dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _infer_entities(event_type: str, payload: dict[str, Any]) -> tuple[int | None, int | None, str | None, int | None]:
    """Derive trainer_id, client_id, subject_type, subject_id from audit payload."""
    trainer_id = _as_int(payload.get("trainer_id"))
    client_id = _as_int(payload.get("client_id"))
    subject_type: str | None = None
    subject_id: int | None = None

    if bid := _as_int(payload.get("booking_id")):
        subject_type, subject_id = "booking", bid
    elif rid := _as_int(payload.get("request_id")):
        subject_type, subject_id = "client_request", rid
    elif iid := _as_int(payload.get("invoice_id")):
        subject_type, subject_id = "invoice", iid
    elif event_type.startswith("trainer.") and trainer_id:
        subject_type, subject_id = "trainer", trainer_id
    elif event_type.startswith("legal.") and (doc_id := _as_int(payload.get("document_id"))):
        subject_type, subject_id = "legal_document", doc_id

    return trainer_id, client_id, subject_type, subject_id


def _as_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def schedule_audit_persist(record: dict[str, Any]) -> None:
    """Fire-and-forget DB persist; safe to call from sync ``audit_log``."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_persist_audit_record(record), name="platform_audit_persist")


async def _persist_audit_record(record: dict[str, Any]) -> None:
    try:
        async with async_session_factory() as session:
            await insert_platform_audit_from_record(session, record)
            await session.commit()
    except Exception:
        logger.exception("platform audit persist failed event=%s", record.get("event"))


async def insert_platform_audit_from_record(session: AsyncSession, record: dict[str, Any]) -> int | None:
    event_type = str(record.get("event") or "")
    actor_type = str(record.get("actor_type") or "")
    actor_id = str(record.get("actor_id") or "")
    payload = dict(record.get("payload") or {})
    source = actor_type or "system"
    trainer_id, client_id, subject_type, subject_id = _infer_entities(event_type, payload)

    params: dict[str, Any] = {
        "event_type": event_type[:64],
        "actor_type": actor_type[:32],
        "actor_id": actor_id[:64],
        "source": source[:32],
        "trainer_id": trainer_id,
        "client_id": client_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": _json_dumps(payload),
    }
    r = await session.execute(
        text(
            """
            INSERT INTO platform_audit_events (
                event_type, actor_type, actor_id, source,
                trainer_id, client_id, subject_type, subject_id, payload
            )
            VALUES (
                :event_type, :actor_type, :actor_id, :source,
                :trainer_id, :client_id, :subject_type, :subject_id, CAST(:payload AS jsonb)
            )
            RETURNING id
            """
        ),
        params,
    )
    row = r.fetchone()
    return int(row[0]) if row else None


async def list_platform_audit_events_for_admin(
    session: AsyncSession,
    *,
    limit: int = 50,
    before_id: int | None = None,
    event_type: str | None = None,
    trainer_id: int | None = None,
) -> dict[str, Any]:
    """Chronological activity feed for admin Mini App (newest first)."""
    limit = max(1, min(limit, 100))
    clauses = ["1=1"]
    params: dict[str, Any] = {"lim": limit + 1}

    if before_id is not None:
        clauses.append("e.id < :before_id")
        params["before_id"] = before_id
    if event_type:
        clauses.append("e.event_type = :event_type")
        params["event_type"] = event_type
    if trainer_id is not None:
        clauses.append("e.trainer_id = :trainer_id")
        params["trainer_id"] = trainer_id

    where = " AND ".join(clauses)
    r = await session.execute(
        text(
            f"""
            SELECT
                e.id,
                e.occurred_at,
                e.event_type,
                e.actor_type,
                e.actor_id,
                e.source,
                e.trainer_id,
                e.client_id,
                e.subject_type,
                e.subject_id,
                e.payload,
                NULLIF(TRIM(CONCAT(COALESCE(tp.first_name, ''), ' ', COALESCE(tp.last_name, ''))), '')
                    AS trainer_name,
                NULLIF(TRIM(CONCAT(COALESCE(c.first_name, ''), ' ', COALESCE(c.last_name, ''))), '')
                    AS client_name
            FROM platform_audit_events e
            LEFT JOIN trainer_profiles tp ON tp.trainer_id = e.trainer_id
            LEFT JOIN clients c ON c.id = e.client_id
            WHERE {where}
            ORDER BY e.id DESC
            LIMIT :lim
            """
        ),
        params,
    )
    rows = r.fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]

    events: list[dict[str, Any]] = []
    for row in rows:
        (
            eid,
            occurred_at,
            ev_type,
            actor_type,
            actor_id,
            source,
            tid,
            cid,
            subject_type,
            subject_id,
            payload,
            trainer_name,
            client_name,
        ) = row
        pl = payload if isinstance(payload, dict) else {}
        events.append(
            {
                "id": int(eid),
                "occurred_at": _iso(occurred_at),
                "event_type": str(ev_type),
                "event_label_ru": event_label_ru(str(ev_type)),
                "actor_type": str(actor_type),
                "actor_id": str(actor_id),
                "actor_label_ru": _actor_label_ru(str(actor_type), str(actor_id), trainer_name, client_name),
                "source": str(source),
                "trainer_id": int(tid) if tid is not None else None,
                "trainer_label_ru": _trainer_label(tid, trainer_name),
                "client_id": int(cid) if cid is not None else None,
                "client_label_ru": _client_label(cid, client_name),
                "subject_type": subject_type,
                "subject_id": int(subject_id) if subject_id is not None else None,
                "payload": pl,
                "detail_ru": _detail_ru(str(ev_type), pl, subject_type, subject_id),
            }
        )

    return {"events": events, "has_more": has_more}


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _actor_label_ru(
    actor_type: str,
    actor_id: str,
    trainer_name: str | None,
    client_name: str | None,
) -> str:
    base = ACTOR_LABELS_RU.get(actor_type, actor_type)
    if actor_type == "trainer_bot" and trainer_name:
        return f"{base} · {trainer_name.strip()}"
    if actor_type == "client_bot" and client_name:
        return f"{base} · {client_name.strip()}"
    if actor_id and actor_id not in ("api", "webapp_trainer_profile"):
        return f"{base} · tg {actor_id}"
    return base


def _trainer_label(trainer_id: object | None, name: str | None) -> str | None:
    if trainer_id is None:
        return None
    if name and str(name).strip():
        return f"{str(name).strip()} (#{int(trainer_id)})"
    return f"Тренер #{int(trainer_id)}"


def _client_label(client_id: object | None, name: str | None) -> str | None:
    if client_id is None:
        return None
    if name and str(name).strip():
        return f"{str(name).strip()} (#{int(client_id)})"
    return f"Клиент #{int(client_id)}"


def _detail_ru(
    event_type: str,
    payload: dict[str, Any],
    subject_type: str | None,
    subject_id: int | None,
) -> str | None:
    parts: list[str] = []
    if subject_type and subject_id is not None:
        parts.append(f"{subject_type} #{subject_id}")
    if status := payload.get("status"):
        parts.append(f"status={status}")
    if week := payload.get("week"):
        parts.append(f"неделя={week}")
    if slots := payload.get("slots_count"):
        parts.append(f"слотов={slots}")
    if not parts:
        return None
    return " · ".join(parts)
