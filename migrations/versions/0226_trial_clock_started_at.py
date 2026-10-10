"""trainer_subscriptions.trial_clock_started_at — delay trial countdown until first real completed.

Revision ID: 0226_trial_clock_started_at
Revises: 0225_trainer_services_is_online
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0226_trial_clock_started_at"
down_revision = "0225_trainer_services_is_online"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_subscriptions",
        sa.Column("trial_clock_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing trial rows already had a ticking clock — treat started_at as clock start.
    # Pending (not yet ticking) rows are only created by new code after this migration.
    # Sentinel/far expires (year >= 2090) keep NULL so they stay pending if any exist.
    op.execute(
        """
        UPDATE trainer_subscriptions AS ts
        SET trial_clock_started_at = ts.started_at
        FROM subscription_plans sp
        WHERE ts.plan_id = sp.id
          AND sp.is_trial = true
          AND ts.trial_clock_started_at IS NULL
          AND EXTRACT(YEAR FROM ts.expires_at AT TIME ZONE 'UTC') < 2090
        """
    )


def downgrade() -> None:
    op.drop_column("trainer_subscriptions", "trial_clock_started_at")
