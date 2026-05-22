"""Append-only platform audit log for admin activity timeline."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0154_platform_audit"
down_revision = "0153_client_booking_daypart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subject_type", sa.String(length=32), nullable=True),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_audit_occurred_at",
        "platform_audit_events",
        [sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_platform_audit_trainer_time",
        "platform_audit_events",
        ["trainer_id", sa.text("occurred_at DESC")],
        postgresql_where=sa.text("trainer_id IS NOT NULL"),
    )
    op.create_index(
        "ix_platform_audit_event_time",
        "platform_audit_events",
        ["event_type", sa.text("occurred_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_audit_event_time", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_trainer_time", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_occurred_at", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")
