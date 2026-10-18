"""Закрепы подборки «Для вас»: до трёх мест на город.

Revision ID: 0243_city_picks
Revises: 0242_client_broadcasts
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0243_city_picks"
down_revision = "0242_client_broadcasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "city_picks",
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("city_id", "position", name="pk_city_picks"),
        sa.UniqueConstraint("city_id", "arena_id", name="uq_city_picks_city_arena"),
        sa.CheckConstraint("position BETWEEN 1 AND 3", name="ck_city_picks_position"),
    )


def downgrade() -> None:
    op.drop_table("city_picks")
