"""Trainer schedule: weekly templates and concrete slots for booking.

Revision ID: 0010_schedule
Revises: 0009_cities_service
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_schedule"
down_revision = "0009_cities_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_schedule_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_trainer_schedule_templates_trainer_id"),
        "trainer_schedule_templates",
        ["trainer_id"],
        unique=False,
    )

    op.create_table(
        "slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("status", sa.String(16), server_default="available", nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_slots_trainer_id"), "slots", ["trainer_id"], unique=False)
    op.create_index(op.f("ix_slots_slot_date_status"), "slots", ["slot_date", "status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_slots_slot_date_status"), table_name="slots")
    op.drop_index(op.f("ix_slots_trainer_id"), table_name="slots")
    op.drop_table("slots")
    op.drop_index(op.f("ix_trainer_schedule_templates_trainer_id"), table_name="trainer_schedule_templates")
    op.drop_table("trainer_schedule_templates")
