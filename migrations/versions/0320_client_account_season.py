"""Имя, заданное человеком, и «мой каток» на аккаунте (TASK-367).

``hockey_players.name_set_by_user`` — ход больше не затирает имя из «Я».
``client_account_prefs`` — один каток на тот же ключ, что у игрока «Кто кого».

Revision ID: 0320_client_account_season
Revises: 0319_hockey_source_status
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0320_client_account_season"
down_revision = "0319_hockey_source_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hockey_players",
        sa.Column("name_set_by_user", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_table(
        "client_account_prefs",
        sa.Column("account_key", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column(
            "home_arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("client_account_prefs")
    op.drop_column("hockey_players", "name_set_by_user")
