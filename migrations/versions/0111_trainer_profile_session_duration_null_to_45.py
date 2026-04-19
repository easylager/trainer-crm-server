"""Backfill trainer_profiles.session_duration_minutes NULL → 45 (product default)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0111_session_duration_null_45"
down_revision = "0110_trainer_is_catalog_visible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE trainer_profiles SET session_duration_minutes = 45 WHERE session_duration_minutes IS NULL")
    )


def downgrade() -> None:
    # Cannot distinguish rows that were NULL before backfill.
    pass
