"""Trainer confirm reminder flag for bookings.

Revision ID: 0035_booking_confirm_reminder
Revises: 0034_recurring_client_slots
"""

from alembic import op
import sqlalchemy as sa


revision = "0035_booking_confirm_reminder"
down_revision = "0034_recurring_client_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "trainer_confirm_reminder_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bookings", "trainer_confirm_reminder_sent_at")

