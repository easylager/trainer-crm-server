"""Bookings: who/why cancelled — excludes system recurring/roster detach from KPI churn.

Revision ID: 0150_booking_cancellation_source
Revises: 0149_reminder_merge
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0150_booking_cancellation_source"
down_revision = "0149_reminder_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("cancellation_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "cancellation_source")
