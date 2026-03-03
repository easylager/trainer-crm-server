"""Add trainer_daily_request_reminder_sent: one row per trainer per day for daily request digest.

Revision ID: 0032_trainer_daily_reminder
Revises: 0031_no_response_reminder
"""
from alembic import op
import sqlalchemy as sa


revision = "0032_trainer_daily_reminder"
down_revision = "0031_no_response_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_daily_request_reminder_sent",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("sent_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trainer_id", "sent_date", name="uq_trainer_daily_reminder"),
    )
    op.create_index(
        op.f("ix_trainer_daily_request_reminder_sent_trainer_id"),
        "trainer_daily_request_reminder_sent",
        ["trainer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_trainer_daily_request_reminder_sent_trainer_id"),
        table_name="trainer_daily_request_reminder_sent",
    )
    op.drop_table("trainer_daily_request_reminder_sent")
