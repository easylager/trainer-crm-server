"""Default arena_schedule_presets hour window 06–23 (was 08–21) for new rows.

Existing rows are unchanged; application fallbacks use the same bounds when no preset.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0137_default_hour_window_6_23"
down_revision = "0136_zamok_arena_hourly_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "arena_schedule_presets",
        "hour_start",
        existing_type=sa.SmallInteger(),
        server_default="6",
        existing_nullable=False,
    )
    op.alter_column(
        "arena_schedule_presets",
        "hour_end",
        existing_type=sa.SmallInteger(),
        server_default="23",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "arena_schedule_presets",
        "hour_start",
        existing_type=sa.SmallInteger(),
        server_default="8",
        existing_nullable=False,
    )
    op.alter_column(
        "arena_schedule_presets",
        "hour_end",
        existing_type=sa.SmallInteger(),
        server_default="21",
        existing_nullable=False,
    )
