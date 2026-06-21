"""Reliable outbox for booking lifecycle party notifications (client/trainer).

Revision ID: 0173_booking_party_notifications
Revises: 0172_canonical_org_format
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0173_booking_party_notifications"
down_revision = "0172_canonical_org_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_party_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("recipient_role", sa.String(16), nullable=False),
        sa.Column("recipient_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", "kind", name="uq_booking_party_notif_booking_kind"),
    )
    op.create_index(
        "ix_booking_party_notif_pending",
        "booking_party_notifications",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_booking_party_notif_pending", table_name="booking_party_notifications")
    op.drop_table("booking_party_notifications")
