"""Align welcome trial length with landing promise (14 days).

Revision ID: 0177_welcome_trial_14_days
Revises: 0176_care_pulses
"""

from alembic import op


revision = "0177_welcome_trial_14_days"
down_revision = "0176_care_pulses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE platform_settings
        SET value_int = 14
        WHERE key = 'welcome_trial_period_days'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE platform_settings
        SET value_int = 21
        WHERE key = 'welcome_trial_period_days'
        """
    )
