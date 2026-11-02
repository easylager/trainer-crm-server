"""Game views pick up columns added after they were created (previous_starts_at from 0294).

``CREATE VIEW ... SELECT *`` freezes the column list at creation time; ``CREATE OR REPLACE``
appends the new hockey_matches columns at the end, which Postgres allows.

Revision ID: 0301_game_views_refresh
Revises: 0300_winter_pending_confirm
"""

from __future__ import annotations

from alembic import op

revision = "0301_game_views_refresh"
down_revision = "0300_winter_pending_confirm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # kk_matches stays frozen on purpose (0292): the Dinamo checker needs no new columns.
    op.execute("CREATE OR REPLACE VIEW game_matches AS SELECT * FROM hockey_matches")


def downgrade() -> None:
    # Back to the 0292 shape: without the 0294 columns, so 0294 can drop them.
    cols = op.get_bind().exec_driver_sql(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'hockey_matches' "
        "AND table_schema = current_schema() AND column_name NOT IN ('previous_starts_at', 'missed_runs') ORDER BY ordinal_position"
    ).scalars().all()
    op.execute("DROP VIEW game_matches")
    op.execute(f"CREATE VIEW game_matches AS SELECT {', '.join(cols)} FROM hockey_matches")
