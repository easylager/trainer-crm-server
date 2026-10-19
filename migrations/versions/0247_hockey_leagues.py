"""Игра «Кто кого»: лиги друзей и участники (TASK-298).

Revision ID: 0247_hockey_leagues
Revises: 0246_hockey_picks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0247_hockey_leagues"
down_revision = "0246_hockey_picks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_leagues",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(28), nullable=False),
        sa.Column(
            "owner_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invite_code", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("invite_code", name="uq_hockey_leagues_invite_code"),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 28", name="ck_hockey_leagues_name"),
    )
    op.create_table(
        "hockey_league_members",
        sa.Column(
            "league_id",
            sa.BigInteger(),
            sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("league_id", "player_key", name="pk_hockey_league_members"),
    )
    op.create_index("ix_hockey_league_members_player", "hockey_league_members", ["player_key"])


def downgrade() -> None:
    op.drop_index("ix_hockey_league_members_player", table_name="hockey_league_members")
    op.drop_table("hockey_league_members")
    op.drop_table("hockey_leagues")
