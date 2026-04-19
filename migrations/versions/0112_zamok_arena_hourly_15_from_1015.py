"""ТЦ Замок: hourly grid at :15 (was :10), window from 10:00 (first start 10:15)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0112_zamok_hourly_15_from_1015"
down_revision = "0111_session_duration_null_45"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE arena_schedule_presets AS p
            SET minute_offset = 15, hour_start = 10
            FROM arenas AS a
            WHERE p.arena_id = a.id AND a.name = 'ТЦ Замок'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE arena_schedule_presets AS p
            SET minute_offset = 10, hour_start = 8
            FROM arenas AS a
            WHERE p.arena_id = a.id AND a.name = 'ТЦ Замок'
            """
        )
    )
