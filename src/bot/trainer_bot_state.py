"""Shared mutable state for trainer bot handlers (avoids circular imports with middleware)."""

# Users who tapped support and are expected to send a text message next.
trainer_support_awaiting: set[int] = set()
# Mirrors keys of `_trainer_booking_note_state` in trainer_handlers — gate must allow replies before profile tiers.
trainer_booking_note_awaiting: set[int] = set()
