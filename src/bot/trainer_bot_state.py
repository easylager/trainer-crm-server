"""Shared mutable state for trainer bot handlers (avoids circular imports with middleware)."""

from __future__ import annotations

import time

# Users who tapped support and are expected to send a text message next.
trainer_support_awaiting: set[int] = set()
# Mirrors keys of `_trainer_booking_note_state` in trainer_handlers — gate must allow replies before profile tiers.
trainer_booking_note_awaiting: set[int] = set()
# Mirrors keys of `_booking_decline_state` — optional decline comment after «Отклонить» on pending booking push.
trainer_booking_decline_awaiting: set[int] = set()

# Relay: trainer's next plain-text DM routes to client bot while session open (trainer tg user id → session).
# TTL bounds accidental misroutes if the trainer wandered into other workflows without /cancel.
_RELAY_TRAINER_REPLY_TTL_SEC = 15 * 60
trainer_relay_reply_pending: dict[int, tuple[int, float]] = {}


def set_trainer_relay_reply_pending(trainer_telegram_id: int, session_id: int) -> None:
    trainer_relay_reply_pending[int(trainer_telegram_id)] = (
        int(session_id),
        time.monotonic() + _RELAY_TRAINER_REPLY_TTL_SEC,
    )


def clear_trainer_relay_reply_pending(trainer_telegram_id: int) -> None:
    trainer_relay_reply_pending.pop(int(trainer_telegram_id), None)


def peek_trainer_relay_reply_pending(trainer_telegram_id: int) -> int | None:
    """Return open session id or None if missing/expired (expired entries are dropped)."""
    uid = int(trainer_telegram_id)
    row = trainer_relay_reply_pending.get(uid)
    if not row:
        return None
    sid, deadline = row
    if time.monotonic() > deadline:
        trainer_relay_reply_pending.pop(uid, None)
        return None
    return int(sid)
