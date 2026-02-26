"""Reminders for client bookings: scheduled notifications.

Revision ID: 0018_reminders
Revises: 0017_photo_list_key
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_reminders"
down_revision = "0017_photo_list_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reminders_booking_id"), "reminders", ["booking_id"], unique=False)
    op.create_index(op.f("ix_reminders_client_telegram_id"), "reminders", ["client_telegram_id"], unique=False)
    op.create_index(op.f("ix_reminders_send_at"), "reminders", ["send_at"], unique=False)
    op.create_index("ix_reminders_pending_send_at", "reminders", ["status", "send_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_reminders_pending_send_at", table_name="reminders")
    op.drop_index(op.f("ix_reminders_send_at"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_client_telegram_id"), table_name="reminders")
    op.drop_index(op.f("ix_reminders_booking_id"), table_name="reminders")
    op.drop_table("reminders")

