"""Group cohort RSVP prompts + partial unique index on active bookings per slot/client.

Revision ID: 0090
Revises: 0089
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_attendance_prompts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("training_group_id", sa.Integer(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("response", sa.String(8), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["training_group_id"], ["training_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slot_id", "client_id", name="uq_group_attendance_prompt_slot_client"),
    )
    op.create_index("ix_gap_send_at_status", "group_attendance_prompts", ["send_at", "status"])
    op.create_index("ix_gap_slot_id", "group_attendance_prompts", ["slot_id"])
    op.create_index("ix_gap_client_id", "group_attendance_prompts", ["client_id"])

    # Prevent double seat: one pending/confirmed booking per (slot, client)
    op.execute(
        """
        DELETE FROM bookings b
        WHERE b.status IN ('pending', 'confirmed')
          AND EXISTS (
            SELECT 1 FROM bookings b2
            WHERE b2.slot_id = b.slot_id AND b2.client_id = b.client_id
              AND b2.status IN ('pending', 'confirmed')
              AND b2.id < b.id
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_bookings_slot_client_occupy
        ON bookings (slot_id, client_id)
        WHERE status IN ('pending', 'confirmed')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bookings_slot_client_occupy")
    op.drop_table("group_attendance_prompts")
