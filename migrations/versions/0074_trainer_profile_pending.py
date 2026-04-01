"""Trainer profile text revisions pending moderation (active trainers).

Published data stays in trainer_profiles for catalog until admin approves;
pending edits stored in trainers.profile_pending (JSONB).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0074_trainer_profile_pending"
# Must match revision id in 0073_platform_settings_welcome_trial.py (truncated in that file).
down_revision = "0073_platform_settings_welcom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("profile_pending", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "profile_pending")
