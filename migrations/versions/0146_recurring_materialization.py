"""Recurring client: auto-bookings link + week skips (cancel one week without re-materializing).

Revision ID: 0146_recurring_materialization
Revises: 0145_trainer_relay
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0146_recurring_materialization"
down_revision = "0145_trainer_relay"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column(
            "recurring_client_slot_id",
            sa.Integer(),
            sa.ForeignKey("recurring_client_slots.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_bookings_recurring_client_slot_id"),
        "bookings",
        ["recurring_client_slot_id"],
        unique=False,
    )

    op.create_table(
        "recurring_materialization_week_skips",
        sa.Column("recurring_client_slot_id", sa.Integer(), nullable=False),
        sa.Column("week_start_monday", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recurring_client_slot_id"],
            ["recurring_client_slots.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("recurring_client_slot_id", "week_start_monday"),
    )


def downgrade() -> None:
    op.drop_table("recurring_materialization_week_skips")
    op.drop_index(op.f("ix_bookings_recurring_client_slot_id"), table_name="bookings")
    op.drop_column("bookings", "recurring_client_slot_id")
