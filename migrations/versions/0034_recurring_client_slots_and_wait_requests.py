"""Recurring client slots (regular time) and wait-for-slot requests.

Revision ID: 0034_recurring_client_slots
Revises: 0033_pending_request_booking
"""
from alembic import op
import sqlalchemy as sa


revision = "0034_recurring_client_slots"
down_revision = "0033_pending_request_booking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recurring_client_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),  # 0=Mon .. 6=Sun
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),  # active | paused | cancelled
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_recurring_client_slots_trainer_id"),
        "recurring_client_slots",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_recurring_client_slots_client_id"),
        "recurring_client_slots",
        ["client_id"],
        unique=False,
    )
    # One active recurring slot per (trainer, client, day, time)
    op.create_index(
        "uq_recurring_client_slots_trainer_client_day_time",
        "recurring_client_slots",
        ["trainer_id", "client_id", "day_of_week", "start_time"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "client_slot_wait_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_client_slot_wait_requests_trainer_id"),
        "client_slot_wait_requests",
        ["trainer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_client_slot_wait_requests_client_id"),
        "client_slot_wait_requests",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_client_slot_wait_requests_client_id"),
        table_name="client_slot_wait_requests",
    )
    op.drop_index(
        op.f("ix_client_slot_wait_requests_trainer_id"),
        table_name="client_slot_wait_requests",
    )
    op.drop_table("client_slot_wait_requests")
    op.drop_index(
        "uq_recurring_client_slots_trainer_client_day_time",
        table_name="recurring_client_slots",
    )
    op.drop_index(
        op.f("ix_recurring_client_slots_client_id"),
        table_name="recurring_client_slots",
    )
    op.drop_index(
        op.f("ix_recurring_client_slots_trainer_id"),
        table_name="recurring_client_slots",
    )
    op.drop_table("recurring_client_slots")
