"""Notify client when trainer cancels a booking. Client bot sends from this queue.

Revision ID: 0020_bk_cancel_notif (shortened to fit alembic_version.version_num varchar(32))
Revises: 0019_moderation_feedback
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_bk_cancel_notif"
down_revision = "0019_moderation_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "booking_cancel_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("trainer_display_name", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_booking_cancel_notif_booking_id"),
    )
    op.create_index(
        op.f("ix_booking_cancel_notifications_sent_at"),
        "booking_cancel_notifications",
        ["sent_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_cancel_notifications_sent_at"), table_name="booking_cancel_notifications")
    op.drop_table("booking_cancel_notifications")
