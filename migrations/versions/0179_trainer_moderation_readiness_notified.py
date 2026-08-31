"""Track when trainer profile is ready for moderation notification sent.

Revision ID: 0179_trainer_moderation_readiness_notified
Revises: 0178_trainer_arena_setup
"""

from alembic import op
import sqlalchemy as sa


revision = "0179_trainer_moderation_readiness_notified"
down_revision = "0178_trainer_arena_setup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("moderation_readiness_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "moderation_readiness_notified_at")
