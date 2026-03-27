"""Shared mutable state for trainer bot handlers (avoids circular imports with middleware)."""

# Users who tapped support and are expected to send a text message next.
trainer_support_awaiting: set[int] = set()
