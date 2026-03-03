"""Trainer "will book later" + client notification for trainer-created booking.

Revision ID: 0033_pending_request_booking
Revises: 0032_trainer_daily_reminder
"""
from alembic import op
import sqlalchemy as sa


revision = "0033_pending_request_booking"
down_revision = "0032_trainer_daily_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_pending_request_booking",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_request_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_request_id"], ["client_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "client_request_id", name="uq_trainer_pending_request_booking"),
    )
    op.create_index(
        op.f("ix_trainer_pending_request_booking_trainer_id"),
        "trainer_pending_request_booking",
        ["trainer_id"],
        unique=False,
    )
    op.add_column(
        "bookings",
        sa.Column("client_notified_trainer_booked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bookings", "client_notified_trainer_booked_at")
    op.drop_index(
        op.f("ix_trainer_pending_request_booking_trainer_id"),
        table_name="trainer_pending_request_booking",
    )
    op.drop_table("trainer_pending_request_booking")
