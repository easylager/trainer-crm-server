"""Referral milestones: onboarding and first-booking bonus timestamps on trainer_referrals."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0120_referral_milestone_bonuses"
down_revision = "0119_drop_daily_req_reminder_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_referrals",
        sa.Column("onboarding_bonus_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trainer_referrals",
        sa.Column("first_booking_bonus_granted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_referrals", "first_booking_bonus_granted_at")
    op.drop_column("trainer_referrals", "onboarding_bonus_granted_at")
