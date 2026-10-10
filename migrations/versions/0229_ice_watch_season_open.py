"""Allow season_open on client ice watches.

Revision ID: 0229_ice_watch_season_open
Revises: 0228_client_ice_watches

The kind check from 0228 only listed sessions and schedule_fresh.
A season reminder is a third kind, not a new table.
"""

from __future__ import annotations

from alembic import op

revision = "0229_ice_watch_season_open"
down_revision = "0228_client_ice_watches"
branch_labels = None
depends_on = None

_WATCH_KINDS = ("sessions", "schedule_fresh", "season_open")


def upgrade() -> None:
    op.drop_constraint("ck_client_ice_watches_kind", "client_ice_watches", type_="check")
    op.create_check_constraint(
        "ck_client_ice_watches_kind",
        "client_ice_watches",
        f"watch_kind IN ({', '.join(repr(k) for k in _WATCH_KINDS)})",
    )


def downgrade() -> None:
    op.execute("DELETE FROM client_ice_watches WHERE watch_kind = 'season_open'")
    op.drop_constraint("ck_client_ice_watches_kind", "client_ice_watches", type_="check")
    op.create_check_constraint(
        "ck_client_ice_watches_kind",
        "client_ice_watches",
        "watch_kind IN ('sessions', 'schedule_fresh')",
    )
