"""Slots: capacity for group lessons; bookings: allow multiple rows per slot.

Revision ID: 0082
Revises: 0081
"""
from alembic import op
import sqlalchemy as sa


revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slots",
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint("ck_slots_capacity_positive", "slots", "capacity >= 1")
    op.drop_index(op.f("ix_bookings_slot_id"), table_name="bookings")
    op.create_index(op.f("ix_bookings_slot_id"), "bookings", ["slot_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bookings_slot_id"), table_name="bookings")
    op.create_index(op.f("ix_bookings_slot_id"), "bookings", ["slot_id"], unique=True)
    op.drop_constraint("ck_slots_capacity_positive", "slots", type_="check")
    op.drop_column("slots", "capacity")
