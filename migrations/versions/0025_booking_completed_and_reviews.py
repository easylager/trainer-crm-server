"""Booking lifecycle: status (pending|completed|cancelled), trainer review, client review_text.

Revision ID: 0025_booking_completed_reviews
Revises: 0024_trainer_service_prices
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_booking_completed_reviews"
down_revision = "0024_trainer_service_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bookings",
        sa.Column("status", sa.String(32), nullable=True),
    )
    # Existing rows: mark completed so worker won't send old "leave feedback" to them
    op.execute("UPDATE bookings SET status = 'completed'")
    op.alter_column(
        "bookings",
        "status",
        existing_type=sa.String(32),
        server_default="pending",
        nullable=False,
    )
    op.add_column(
        "bookings",
        sa.Column("trainer_review_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "trainer_ratings",
        sa.Column("review_text", sa.Text(), nullable=True),
    )

    op.create_table(
        "booking_completed_notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("trainer_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("booking_id", name="uq_booking_completed_booking_id"),
    )
    op.create_index("ix_booking_completed_trainer_sent", "booking_completed_notifications", ["trainer_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_booking_completed_trainer_sent", table_name="booking_completed_notifications")
    op.drop_table("booking_completed_notifications")
    op.drop_column("trainer_ratings", "review_text")
    op.drop_column("bookings", "trainer_review_text")
    op.drop_column("bookings", "status")
