"""Catalog prod hygiene (TASK-177): retired-duplicate redirects + expired ice sessions.

* ``arenas.merged_into_arena_id`` — a retired duplicate points at its canonical arena so
  old ``/p/`` URLs answer 301 instead of 404 (data-driven, set by
  ``scripts/catalog_prod_hygiene.py``).
* ``ice_sessions.status`` gains ``expired`` — the TTL loop marks past ``active`` sessions
  instead of leaving them ``active`` until the 14-day delete. Rows are kept for the
  14-day window (recent-history/demand reads), only their status changes.

Revision ID: 0217_catalog_prod_hygiene
Revises: 0216_ice_ops_alerts
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0217_catalog_prod_hygiene"
down_revision = "0216_ice_ops_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arenas",
        sa.Column(
            "merged_into_arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="SET NULL", name="fk_arenas_merged_into_arena_id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_arenas_merged_into_not_self",
        "arenas",
        "merged_into_arena_id IS NULL OR merged_into_arena_id <> id",
    )
    op.drop_constraint("ck_ice_sessions_status", "ice_sessions", type_="check")
    op.create_check_constraint(
        "ck_ice_sessions_status",
        "ice_sessions",
        "status IN ('active', 'cancelled', 'superseded', 'expired')",
    )


def downgrade() -> None:
    op.execute("UPDATE ice_sessions SET status = 'active' WHERE status = 'expired'")
    op.drop_constraint("ck_ice_sessions_status", "ice_sessions", type_="check")
    op.create_check_constraint(
        "ck_ice_sessions_status",
        "ice_sessions",
        "status IN ('active', 'cancelled', 'superseded')",
    )
    op.drop_constraint("ck_arenas_merged_into_not_self", "arenas", type_="check")
    op.drop_column("arenas", "merged_into_arena_id")
