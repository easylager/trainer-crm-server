"""Rate and quota guards for client-initiated bookings (anti-spam, not full DDoS)."""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.config import Settings
from src.shared.rate_limit import RateLimiter

_booking_attempt_limiter: RateLimiter | None = None


def reset_client_booking_limiter_for_tests() -> None:
    """Tests only — rebuild limiter from current env."""
    global _booking_attempt_limiter
    _booking_attempt_limiter = None


def _get_booking_attempt_limiter() -> RateLimiter:
    global _booking_attempt_limiter
    if _booking_attempt_limiter is None:
        s = Settings()
        _booking_attempt_limiter = RateLimiter(
            s.client_booking_rate_max_requests,
            s.client_booking_rate_window_sec,
        )
    return _booking_attempt_limiter


def client_booking_attempt_allowed(telegram_id: int) -> bool:
    """Sliding window cap on booking POST attempts per Telegram user."""
    return _get_booking_attempt_limiter().check_and_consume(int(telegram_id))


async def count_client_future_pending_bookings(
    session: AsyncSession,
    client_id: int,
    *,
    trainer_id: int | None = None,
) -> int:
    """Future slots with status=pending awaiting trainer confirm."""
    params: dict[str, int] = {"cid": client_id}
    trainer_clause = ""
    if trainer_id is not None:
        trainer_clause = " AND b.trainer_id = :tid"
        params["tid"] = trainer_id
    r = await session.execute(
        text(
            f"""
            SELECT COUNT(*) FROM bookings b
            JOIN slots s ON s.id = b.slot_id
            WHERE b.client_id = :cid
              AND b.status = 'pending'
              AND (s.slot_date > CURRENT_DATE
                   OR (s.slot_date = CURRENT_DATE AND s.start_time > CURRENT_TIME))
              {trainer_clause}
            """
        ),
        params,
    )
    row = r.fetchone()
    return int(row[0] or 0) if row else 0


async def client_booking_quota_error(
    session: AsyncSession,
    client_id: int,
    trainer_id: int,
) -> str | None:
    """
    Return Russian user message when pending booking quota exceeded, else None.
    Confirmed future bookings are allowed — only pending floods are capped.
    """
    s = Settings()
    per_trainer = await count_client_future_pending_bookings(session, client_id, trainer_id=trainer_id)
    if per_trainer >= s.client_booking_max_pending_per_trainer:
        return (
            "У вас уже есть заявки на занятия у этого тренера. "
            "Дождитесь подтверждения или отмените лишние."
        )
    total = await count_client_future_pending_bookings(session, client_id)
    if total >= s.client_booking_max_pending_global:
        return (
            "Слишком много неподтверждённых записей. "
            "Дождитесь ответа тренеров или отмените часть заявок."
        )
    return None
