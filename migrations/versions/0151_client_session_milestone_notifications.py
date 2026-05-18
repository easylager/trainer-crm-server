"""Idempotent client pushes for completed-session count milestones (5/10/25).

Revision ID: 0151_session_milestones
Revises: 0150_booking_cancellation_source
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0151_session_milestones"
down_revision = "0150_booking_cancellation_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_session_milestone_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("milestone_target", sa.SmallInteger(), nullable=False),
        sa.Column("completed_total_at_send", sa.Integer(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("milestone_target IN (5, 10, 25)", name="ck_session_milestone_target_allowed"),
        sa.UniqueConstraint("client_id", "milestone_target", name="uq_client_session_milestone"),
    )
    op.create_index(
        "ix_client_session_milestone_notifications_client_id",
        "client_session_milestone_notifications",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_client_session_milestone_notifications_client_id", table_name="client_session_milestone_notifications")
    op.drop_table("client_session_milestone_notifications")
