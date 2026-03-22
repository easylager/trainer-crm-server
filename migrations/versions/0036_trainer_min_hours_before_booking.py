"""Trainer profile: min hours before slot allowed for booking (working hours only).

Revision ID: 0036_trainer_min_hours
Revises: 0035_booking_confirm_reminder
"""

from alembic import op
import sqlalchemy as sa


revision = "0036_trainer_min_hours"
down_revision = "0035_booking_confirm_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column(
            "min_hours_before_booking",
            sa.SmallInteger(),
            nullable=False,
            server_default="3",
        ),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "min_hours_before_booking")
