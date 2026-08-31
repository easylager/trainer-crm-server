"""Trainer arena setup alternatives: mobile format or pending arena request.

Revision ID: 0178_trainer_arena_setup
Revises: 0177_welcome_trial_14_days
"""

from alembic import op
import sqlalchemy as sa


revision = "0178_trainer_arena_setup"
down_revision = "0177_welcome_trial_14_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("arena_work_format", sa.String(32), nullable=True),
    )
    op.add_column(
        "trainers",
        sa.Column("arena_request_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "trainers",
        sa.Column("arena_request_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "arena_request_at")
    op.drop_column("trainers", "arena_request_text")
    op.drop_column("trainers", "arena_work_format")
