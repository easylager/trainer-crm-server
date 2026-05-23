"""
Trainer Telegram push when a client rates a completed session (stars with or without review text).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Literal

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import get_client_id_by_telegram_id, get_trainer_telegram_id
from src.bot import messages as msg
from src.shared.config import Settings

logger = logging.getLogger(__name__)

NotifyKind = Literal["initial", "with_review", "review_added"]


def _duration_minutes(start_time: object, end_time: object) -> int | None:
    try:
        if start_time and end_time and hasattr(start_time, "hour") and hasattr(end_time, "hour"):
            delta = datetime.combine(date.today(), end_time) - datetime.combine(date.today(), start_time)
            mins = int(delta.total_seconds() // 60)
            return mins if mins > 0 else None
    except (TypeError, ValueError):
        pass
    return None


def _slot_labels(slot_date: object, start_time: object) -> tuple[str, str, str]:
    ds = slot_date.strftime("%d.%m") if slot_date and hasattr(slot_date, "strftime") else "—"
    dy = (
        msg.TRAINER_DAYS[slot_date.weekday()]
        if slot_date and hasattr(slot_date, "weekday")
        else ""
    )
    ts = start_time.strftime("%H:%M") if start_time and hasattr(start_time, "strftime") else "—"
    return ds, dy, ts


async def load_stored_rating_row(
    session: AsyncSession,
    *,
    rating_id: int | None = None,
) -> list[dict[str, Any]]:
    """All trainer_ratings rows, or one by id."""
    if rating_id is not None:
        q = """
            SELECT id, trainer_id, client_telegram_id, rating, review_text, created_at
            FROM trainer_ratings
            WHERE id = :rid
        """
        params: dict[str, Any] = {"rid": int(rating_id)}
    else:
        q = """
            SELECT id, trainer_id, client_telegram_id, rating, review_text, created_at
            FROM trainer_ratings
            ORDER BY id
        """
        params = {}
    r = await session.execute(text(q), params)
    return [
        {
            "id": int(row[0]),
            "trainer_id": int(row[1]),
            "client_telegram_id": int(row[2]),
            "rating": int(row[3]),
            "review_text": row[4],
            "created_at": row[5],
        }
        for row in r.fetchall()
    ]


async def resolve_booking_id_for_stored_rating(
    session: AsyncSession,
    *,
    trainer_id: int,
    client_telegram_id: int,
    rating_created_at: object | None = None,
) -> int | None:
    """
    Best-effort booking for a legacy rating row (trainer_ratings has no booking_id).
    Prefer platform_audit trainer.rated with booking_id, else latest completed session.
    """
    r = await session.execute(
        text(
            """
            SELECT subject_id, payload
            FROM platform_audit_events
            WHERE event_type = 'trainer.rated'
              AND trainer_id = :tid
              AND actor_type = 'client_bot'
              AND actor_id = :actor
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        ),
        {"tid": int(trainer_id), "actor": str(int(client_telegram_id))},
    )
    audit_row = r.fetchone()
    if audit_row and audit_row[0]:
        return int(audit_row[0])
    if audit_row and audit_row[1]:
        payload = audit_row[1]
        if isinstance(payload, dict):
            bid = payload.get("booking_id")
            if bid is not None:
                return int(bid)

    params: dict[str, Any] = {
        "tid": int(trainer_id),
        "ctid": int(client_telegram_id),
    }
    created_filter = ""
    if rating_created_at is not None:
        created_filter = "AND s.slot_date <= CAST(:rated_at AS date)"
        params["rated_at"] = rating_created_at

    r2 = await session.execute(
        text(
            f"""
            SELECT b.id
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            WHERE b.trainer_id = :tid
              AND c.telegram_id = :ctid
              AND b.status = 'completed'
              {created_filter}
            ORDER BY s.slot_date DESC, s.start_time DESC
            LIMIT 1
            """
        ),
        params,
    )
    row = r2.fetchone()
    return int(row[0]) if row else None


async def notify_trainer_for_stored_rating(
    session: AsyncSession,
    row: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Send (or preview) trainer push for an existing trainer_ratings row.
    Returns summary dict for CLI logging.
    """
    rating_id = int(row["id"])
    trainer_id = int(row["trainer_id"])
    client_tid = int(row["client_telegram_id"])
    rating = int(row["rating"])
    review_text = (row.get("review_text") or "").strip() or None
    booking_id = await resolve_booking_id_for_stored_rating(
        session,
        trainer_id=trainer_id,
        client_telegram_id=client_tid,
        rating_created_at=row.get("created_at"),
    )

    summary: dict[str, Any] = {
        "rating_id": rating_id,
        "trainer_id": trainer_id,
        "client_telegram_id": client_tid,
        "rating": rating,
        "has_review": bool(review_text),
        "booking_id": booking_id,
        "sent": False,
        "dry_run": dry_run,
    }

    if booking_id is None:
        summary["error"] = "no_completed_booking_found"
        return summary

    if dry_run:
        payload = await load_client_rating_notify_payload(session, booking_id, client_tid)
        summary["client_name"] = (payload or {}).get("client_name")
        summary["trainer_telegram_id"] = (payload or {}).get("trainer_telegram_id")
        return summary

    payload = await load_client_rating_notify_payload(session, booking_id, client_tid)
    if not payload or not payload.get("trainer_telegram_id"):
        summary["error"] = "trainer_telegram_not_linked"
        return summary

    kind: NotifyKind = "with_review" if review_text else "initial"
    await notify_trainer_client_rating(
        session=session,
        booking_id=booking_id,
        client_telegram_id=client_tid,
        rating=rating,
        review_text=review_text,
        kind=kind,
    )
    summary["sent"] = True
    summary["client_name"] = payload.get("client_name")
    summary["trainer_telegram_id"] = payload.get("trainer_telegram_id")
    return summary


async def load_client_rating_notify_payload(
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
) -> dict[str, Any] | None:
    """Completed booking row for client feedback: names, slot, service, arena."""
    cid = await get_client_id_by_telegram_id(session, int(client_telegram_id))
    if cid is None:
        return None
    r = await session.execute(
        text(
            """
            SELECT b.id, b.trainer_id, b.client_id,
                   s.slot_date, s.start_time, s.end_time,
                   TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                   NULLIF(TRIM(sv.name), '') AS service_name,
                   NULLIF(TRIM(ar.name), '') AS arena_name
            FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            JOIN clients c ON c.id = b.client_id
            LEFT JOIN services sv ON sv.id = b.service_id
            LEFT JOIN arenas ar ON ar.id = COALESCE(b.arena_id, s.arena_id)
            WHERE b.id = :bid AND b.client_id = :cid AND b.status = 'completed'
            LIMIT 1
            """
        ),
        {"bid": booking_id, "cid": int(cid)},
    )
    row = r.fetchone()
    if not row:
        return None
    trainer_id = int(row[1])
    trainer_tid = await get_trainer_telegram_id(session, trainer_id)
    client_name = (row[6] or "").strip() or "Клиент"
    return {
        "booking_id": int(row[0]),
        "trainer_id": trainer_id,
        "trainer_telegram_id": trainer_tid,
        "client_id": int(row[2]),
        "slot_date": row[3],
        "start_time": row[4],
        "end_time": row[5],
        "client_name": client_name,
        "service_name": row[7],
        "arena_name": row[8],
    }


def _trainer_client_card_markup(client_id: int) -> InlineKeyboardMarkup | None:
    base = (Settings().webapp_base_url or "").rstrip("/")
    if not base.lower().startswith("https://"):
        return None
    url = f"{base}/webapp/trainer-clients?client_id={int(client_id)}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=msg.TRAINER_BUTTON_CLIENT_CARD_WEBAPP,
                    web_app=WebAppInfo(url=url),
                ),
            ],
        ]
    )


async def notify_trainer_client_rating(
    *,
    session: AsyncSession,
    booking_id: int,
    client_telegram_id: int,
    rating: int,
    review_text: str | None,
    kind: NotifyKind,
) -> None:
    """Best-effort trainer-bot message; logs failures, never raises."""
    settings = Settings()
    if not settings.telegram_bot_token_trainer:
        return

    payload = await load_client_rating_notify_payload(session, booking_id, client_telegram_id)
    if not payload:
        logger.warning(
            "trainer_rating notify: no payload booking_id=%s client_tid=%s",
            booking_id,
            client_telegram_id,
        )
        return

    trainer_tid = payload.get("trainer_telegram_id")
    if not trainer_tid:
        logger.info(
            "trainer_rating notify: no trainer telegram booking_id=%s trainer_id=%s",
            booking_id,
            payload.get("trainer_id"),
        )
        return

    ds, dy, ts = _slot_labels(payload.get("slot_date"), payload.get("start_time"))
    dur = _duration_minutes(payload.get("start_time"), payload.get("end_time"))
    review_clean = (review_text or "").strip() or None

    if kind == "review_added" and review_clean:
        text_html = msg.format_trainer_client_rating_review_added_html(
            client_name=payload["client_name"],
            date=ds,
            day=dy,
            time=ts,
            rating=rating,
            review_text=review_clean,
        )
    else:
        text_html = msg.format_trainer_client_rating_received_html(
            client_name=payload["client_name"],
            date=ds,
            day=dy,
            time=ts,
            duration_minutes=dur,
            service_name=payload.get("service_name"),
            arena_display=payload.get("arena_name"),
            rating=rating,
            review_text=review_clean if kind == "with_review" else None,
        )

    reply_markup = _trainer_client_card_markup(int(payload["client_id"]))
    bot = Bot(
        token=settings.telegram_bot_token_trainer,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(
            chat_id=int(trainer_tid),
            text=text_html,
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(
            "Failed trainer rating notification booking_id=%s trainer_id=%s kind=%s",
            booking_id,
            payload.get("trainer_id"),
            kind,
        )
    finally:
        await bot.session.close()
