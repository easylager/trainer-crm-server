"""Trainer: timestamp when «предложите повтор» wrap-up push was sent (last minute before slot end)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0114_booking_wrapup_ts"
down_revision = "0113_invite_copy_ts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("trainer_session_wrapup_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "trainer_session_wrapup_sent_at")
