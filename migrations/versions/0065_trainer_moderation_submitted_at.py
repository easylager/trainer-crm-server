"""Trainer moderation queue: timestamp of last successful submit (idempotent resubmit rules)."""
from alembic import op
import sqlalchemy as sa


revision = "0065_trainer_mod_submitted"
down_revision = "0064_trainer_education_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("moderation_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "moderation_submitted_at")
