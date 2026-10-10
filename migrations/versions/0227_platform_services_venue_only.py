"""Platform catalog services are venue-only.

Revision ID: 0227_platform_services_venue
Revises: 0226_trial_clock_started_at

Services we author (created_by_trainer_id IS NULL) cannot be offered online.
Resync trainer_profiles.online_enabled from whatever online offerings remain.
"""

from __future__ import annotations

from alembic import op

revision = "0227_platform_services_venue"
down_revision = "0226_trial_clock_started_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE trainer_services ts
        SET is_online = false
        FROM services s
        WHERE ts.service_id = s.id
          AND s.created_by_trainer_id IS NULL
          AND COALESCE(ts.is_online, false)
        """
    )
    op.execute(
        """
        UPDATE trainer_profiles p
        SET online_enabled = EXISTS (
            SELECT 1 FROM trainer_services ts
            WHERE ts.trainer_id = p.trainer_id
              AND COALESCE(ts.is_online, false)
        )
        """
    )


def downgrade() -> None:
    # The previous online flags on platform services are not recoverable.
    pass
