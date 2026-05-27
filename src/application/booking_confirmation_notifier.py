"""
Booking confirmation notifier adapter — Telegram today; email/push later.

Extracted from the monolith POST handler so channels can be swapped without changing API shape.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.booking_use_cases import generate_reminders_for_booking


@runtime_checkable
class BookingConfirmationNotifier(Protocol):
    """Delivers post-booking confirmation side-effects (reminders, push, email)."""

    async def notify_booking_created(
        self,
        session: AsyncSession,
        *,
        booking_id: int,
        telegram_id: int,
        trainer_id: int,
        service_id: int,
    ) -> None: ...


class TelegramBookingConfirmationNotifier:
    """Default: existing reminder + trainer pending notify pipeline."""

    async def notify_booking_created(
        self,
        session: AsyncSession,
        *,
        booking_id: int,
        telegram_id: int,
        trainer_id: int,
        service_id: int,
    ) -> None:
        await generate_reminders_for_booking(session, booking_id)


_default_notifier: BookingConfirmationNotifier = TelegramBookingConfirmationNotifier()


def get_booking_confirmation_notifier() -> BookingConfirmationNotifier:
    return _default_notifier
