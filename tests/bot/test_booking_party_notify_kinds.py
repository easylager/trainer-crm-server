"""Unit tests for booking party immediate delivery kind filtering."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.application.booking_party_notifications import (
    KIND_CLIENT_CANCEL_CONFIRM,
    KIND_CLIENT_CANCEL_TRAINER,
)
from src.bot.booking_party_notify import try_deliver_booking_party_notifications_for_booking


@pytest.mark.asyncio
async def test_try_deliver_respects_kinds_filter() -> None:
    session = MagicMock()
    trainer_bot = MagicMock()
    client_bot = MagicMock()
    rows = [
        {
            "id": 1,
            "booking_id": 10,
            "kind": KIND_CLIENT_CANCEL_TRAINER,
            "recipient_role": "trainer",
            "recipient_telegram_id": 111,
            "payload": {},
            "attempt_count": 0,
        },
        {
            "id": 2,
            "booking_id": 10,
            "kind": KIND_CLIENT_CANCEL_CONFIRM,
            "recipient_role": "client",
            "recipient_telegram_id": 222,
            "payload": {},
            "attempt_count": 0,
        },
    ]
    with patch(
        "src.bot.booking_party_notify.list_pending_booking_party_notifications_for_booking",
        new=AsyncMock(return_value=rows),
    ), patch(
        "src.bot.booking_party_notify.deliver_booking_party_notification_row",
        new=AsyncMock(return_value=True),
    ) as deliver:
        result = await try_deliver_booking_party_notifications_for_booking(
            session,
            10,
            trainer_bot=trainer_bot,
            client_bot=client_bot,
            kinds={KIND_CLIENT_CANCEL_TRAINER},
        )
    assert KIND_CLIENT_CANCEL_TRAINER in result
    assert KIND_CLIENT_CANCEL_CONFIRM not in result
    assert deliver.await_count == 1
    assert deliver.await_args.args[1]["kind"] == KIND_CLIENT_CANCEL_TRAINER
