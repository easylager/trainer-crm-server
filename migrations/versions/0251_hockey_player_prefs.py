"""Игра «Кто кого»: личные настройки игрока — скрыть строку игры на матчах (TASK-304).

Revision ID: 0251_hockey_player_prefs
Revises: 0250_hockey_fifa_points
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0251_hockey_player_prefs"
down_revision = "0250_hockey_fifa_points"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_player_prefs",
        sa.Column("player_key", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("kk_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hockey_player_prefs")
