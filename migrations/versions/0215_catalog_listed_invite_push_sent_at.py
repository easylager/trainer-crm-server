"""One-time push after first catalog listing while still no real bookings."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0215_catalog_listed_invite_push"
down_revision = "0214_trainer_created_cities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("catalog_listed_invite_push_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Already in catalog (or got a manual founder push on prod) — no retroactive auto-send.
    op.execute(
        """
        UPDATE trainer_profiles tp
        SET catalog_listed_invite_push_sent_at = COALESCE(
            tp.catalog_listed_invite_push_sent_at, NOW()
        )
        FROM trainers t
        WHERE t.id = tp.trainer_id
          AND (
            t.catalog_state = 'published'
            OR t.id = 55
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE trainer_profiles
        DROP COLUMN IF EXISTS catalog_listed_invite_push_sent_at
        """
    )
