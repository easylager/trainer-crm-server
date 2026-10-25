"""ice_schedule_waves: when a rink published new schedule days (TASK-329).

One row = the rink's horizon (max local_date of future active public_skate/open_ice
sessions) grew after a parser publish or an admin save. ``seed`` is the first row
per rink — a reference point, never counted as a wave. ``backfill`` rows are
reconstructed from ice_scrape_runs and carry no horizons.

Revision ID: 0268_ice_schedule_waves
Revises: 0267_arena_facts_batch3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0268_ice_schedule_waves"
down_revision = "0267_arena_facts_batch3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_schedule_waves",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("horizon_before", sa.Date(), nullable=True),
        sa.Column("horizon_after", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "source IN ('parser', 'admin', 'seed', 'backfill')",
            name="ck_ice_schedule_waves_source",
        ),
    )
    op.create_index(
        "ix_ice_schedule_waves_arena_detected",
        "ice_schedule_waves",
        ["arena_id", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ice_schedule_waves_arena_detected", table_name="ice_schedule_waves")
    op.drop_table("ice_schedule_waves")
