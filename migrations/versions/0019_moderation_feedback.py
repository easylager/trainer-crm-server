"""Store moderation feedback for trainer (e.g. "нужны правки"); site shows it on profile.

Revision ID: 0019_moderation_feedback
Revises: 0018_reminders
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_moderation_feedback"
down_revision = "0018_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("moderation_feedback", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "moderation_feedback")
