"""Trial ROI recap notification idempotency.

Revision ID: 0126_trial_roi_recap
Revises: 0125_recovery_nudges
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "0126_trial_roi_recap"
down_revision = "0125_recovery_nudges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_subscriptions",
        sa.Column("trial_roi_recap_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_subscriptions", "trial_roi_recap_sent_at")
