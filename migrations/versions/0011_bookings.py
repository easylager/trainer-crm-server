"""Bookings: slot + client telegram, phone, comment; notified_at for trainer push.

Revision ID: 0011_bookings
Revises: 0010_schedule
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_bookings"
down_revision = "0010_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("client_phone", sa.String(32), nullable=False),
        sa.Column("client_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["slot_id"], ["slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_bookings_client_telegram_id"), "bookings", ["client_telegram_id"], unique=False)
    op.create_index(op.f("ix_bookings_trainer_id"), "bookings", ["trainer_id"], unique=False)
    op.create_index(op.f("ix_bookings_slot_id"), "bookings", ["slot_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_bookings_slot_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_trainer_id"), table_name="bookings")
    op.drop_index(op.f("ix_bookings_client_telegram_id"), table_name="bookings")
    op.drop_table("bookings")
