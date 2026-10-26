"""Игра «Кто кого»: гонки месяца, короны, клуб у лиги, просмотр итогов (TASK-334, PDEC-027).

Revision ID: 0270_hockey_races
Revises: 0269_ice_watch_delivery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0270_hockey_races"
down_revision = "0269_ice_watch_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_races",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("club", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="month"),
        sa.Column("title", sa.String(40), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("points_rule", sa.String(16), nullable=False, server_default="fifa_v1"),
        sa.Column("calendar_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("club", "kind", "starts_at", name="uq_hockey_races_club_kind_start"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_hockey_races_window"),
    )
    op.create_table(
        "hockey_crowns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("race_id", sa.Integer(), sa.ForeignKey("hockey_races.id", ondelete="CASCADE"), nullable=False),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"), nullable=True),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("exact", sa.Integer(), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Корона одна на человека в гонке и таблице; NULL лиги — общая таблица.
    op.execute(
        "CREATE UNIQUE INDEX uq_hockey_crowns_race_scope_player "
        "ON hockey_crowns (race_id, COALESCE(league_id, 0), player_key)"
    )
    op.create_index("ix_hockey_crowns_league", "hockey_crowns", ["league_id"])
    op.create_table(
        "hockey_race_seen",
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("race_id", sa.Integer(), sa.ForeignKey("hockey_races.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "hockey_leagues",
        sa.Column("club", sa.String(64), nullable=False, server_default="Динамо-Минск"),
    )


def downgrade() -> None:
    op.drop_column("hockey_leagues", "club")
    op.drop_table("hockey_race_seen")
    op.drop_index("ix_hockey_crowns_league", table_name="hockey_crowns")
    op.execute("DROP INDEX IF EXISTS uq_hockey_crowns_race_scope_player")
    op.drop_table("hockey_crowns")
    op.drop_table("hockey_races")
