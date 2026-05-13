"""Reminder rows may cover several same-day bookings (merged client push).

Revision ID: 0149_reminders_merged_booking_ids
Revises: 0148_client_family_access
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0149_reminder_merge"
down_revision = "0148_client_family_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("merged_booking_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reminders", "merged_booking_ids")
