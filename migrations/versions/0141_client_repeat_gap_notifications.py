"""Dedupe client «repeat same time» trainer pings when no exact slot exists but calendar is free.

Revision ID: 0141_client_repeat_gap_notifications
Revises: 0140_schedule_grid_remove_five
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0141_client_repeat_gap_notif"
down_revision = "0140_schedule_grid_remove_five"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_repeat_gap_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("target_slot_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "booking_id",
            "target_slot_date",
            name="uq_client_repeat_gap_notifications_booking_target_date",
        ),
    )
    op.create_index(
        op.f("ix_client_repeat_gap_notifications_booking_id"),
        "client_repeat_gap_notifications",
        ["booking_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_client_repeat_gap_notifications_booking_id"), table_name="client_repeat_gap_notifications")
    op.drop_table("client_repeat_gap_notifications")
