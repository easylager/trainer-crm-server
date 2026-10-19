"""Korona sales snapshots for Zamok calibration (TASK-295).

Revision ID: 0240_ice_sales_snapshots
Revises: 0239_session_load_rules
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0240_ice_sales_snapshots"
down_revision = "0239_session_load_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_sales_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("arena_id", sa.Integer(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("starts_at_local", sa.Time(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("sold", sa.Integer(), nullable=False),
        sa.Column("held", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.CheckConstraint("capacity >= 0", name="ck_ice_sales_snapshots_capacity"),
        sa.CheckConstraint("sold >= 0", name="ck_ice_sales_snapshots_sold"),
        sa.CheckConstraint("held >= 0", name="ck_ice_sales_snapshots_held"),
        sa.CheckConstraint("source IN ('korona')", name="ck_ice_sales_snapshots_source"),
        sa.ForeignKeyConstraint(["arena_id"], ["arenas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ice_sales_snapshots_session_observed",
        "ice_sales_snapshots",
        ["arena_id", "local_date", "starts_at_local", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ice_sales_snapshots_session_observed", table_name="ice_sales_snapshots")
    op.drop_table("ice_sales_snapshots")
