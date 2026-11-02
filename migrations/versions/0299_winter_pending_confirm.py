"""Winter rinks: "flooded" only with admin/source confirmation (owner decision 02.11).

People's marks no longer set "flooded" by themselves: the engine keeps the public state "waiting" and raises
``pending_confirm``; an admin queue item ``confirm_flood`` asks the admin. ``flood_floor_at`` is the moment of the
last admin/source decision: marks older than it are already accounted for and do not raise pending again.

Revision ID: 0299_winter_pending_confirm
Revises: 0298_zhodino_sdyushor_parser
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0299_winter_pending_confirm"
down_revision = "0298_zhodino_sdyushor_parser"
branch_labels = None
depends_on = None

_OLD = "kind IN ('gone', 'dispute', 'photo_first', 'new_point')"
_NEW = "kind IN ('gone', 'dispute', 'photo_first', 'new_point', 'confirm_flood')"


def upgrade() -> None:
    op.add_column(
        "seasonal_rink_seasons",
        sa.Column("pending_confirm", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("seasonal_rink_seasons", sa.Column("flood_floor_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("ck_seasonal_moderation_kind", "seasonal_moderation_items", type_="check")
    op.create_check_constraint("ck_seasonal_moderation_kind", "seasonal_moderation_items", _NEW)


def downgrade() -> None:
    op.execute("DELETE FROM seasonal_moderation_items WHERE kind = 'confirm_flood'")
    op.drop_constraint("ck_seasonal_moderation_kind", "seasonal_moderation_items", type_="check")
    op.create_check_constraint("ck_seasonal_moderation_kind", "seasonal_moderation_items", _OLD)
    op.drop_column("seasonal_rink_seasons", "flood_floor_at")
    op.drop_column("seasonal_rink_seasons", "pending_confirm")
