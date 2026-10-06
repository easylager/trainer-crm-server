"""TASK-204: honest arena schedule mode (auto / phone / season_closed).

Revision ID: 0222_arena_schedule_mode
Revises: 0221_arena_timezone_backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0222_arena_schedule_mode"
down_revision = "0221_arena_timezone_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arena_profiles",
        sa.Column("schedule_mode", sa.String(length=20), nullable=False, server_default="auto"),
    )
    op.add_column("arena_profiles", sa.Column("reopen_date", sa.Date(), nullable=True))
    op.add_column("arena_profiles", sa.Column("schedule_mode_note", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_arena_profiles_schedule_mode",
        "arena_profiles",
        "schedule_mode IN ('auto', 'phone', 'season_closed')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_arena_profiles_schedule_mode", "arena_profiles", type_="check")
    op.drop_column("arena_profiles", "schedule_mode_note")
    op.drop_column("arena_profiles", "reopen_date")
    op.drop_column("arena_profiles", "schedule_mode")
