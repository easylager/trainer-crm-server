"""Игра «Кто кого»: игроки и ходы на матчи Динамо-Минск (TASK-297).

Revision ID: 0245_hockey_picks
Revises: 0244_hockey_matches
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0245_hockey_picks"
down_revision = "0244_hockey_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_players",
        sa.Column("player_key", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("display_name", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("char_length(display_name) BETWEEN 1 AND 40", name="ck_hockey_players_name"),
    )
    op.create_table(
        "hockey_picks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "match_id",
            sa.Integer(),
            sa.ForeignKey("hockey_matches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("home_score", sa.SmallInteger(), nullable=True),
        sa.Column("away_score", sa.SmallInteger(), nullable=True),
        sa.Column("points", sa.SmallInteger(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("match_id", "player_key", name="uq_hockey_picks_match_player"),
        sa.CheckConstraint("side IN ('home', 'away')", name="ck_hockey_picks_side"),
        sa.CheckConstraint("(home_score IS NULL) = (away_score IS NULL)", name="ck_hockey_picks_score_pair"),
        sa.CheckConstraint(
            "home_score IS NULL OR (home_score >= 0 AND away_score >= 0 AND home_score <> away_score"
            " AND (side = 'home') = (home_score > away_score))",
            name="ck_hockey_picks_score_side",
        ),
        sa.CheckConstraint("points IS NULL OR points IN (0, 1, 5)", name="ck_hockey_picks_points"),
    )
    op.create_index("ix_hockey_picks_player", "hockey_picks", ["player_key"])


def downgrade() -> None:
    op.drop_index("ix_hockey_picks_player", table_name="hockey_picks")
    op.drop_table("hockey_picks")
    op.drop_table("hockey_players")
