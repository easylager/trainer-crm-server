"""Матчи Экстралиги в hockey_matches, таблица лиги и представление kk_matches (TASK-340, PDEC-029).

Матчи Экстралиги ложатся в ту же таблицу, что матчи Динамо: на неё завязаны «Ты пойдёшь?», компании
и приглашения на матч. Игра «Кто кого» остаётся только на Динамо — её модули читают ``kk_matches``,
где только source='hcdinamo'. Представление простое (одна таблица, без агрегатов) — Postgres даёт
в него и UPDATE.

Revision ID: 0280_extraliga_matches
Revises: 0279_place_suggestions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0280_extraliga_matches"
down_revision = "0279_place_suggestions"
branch_labels = None
depends_on = None

# Держать в синхроне с src/infrastructure/db/models.py (HockeyMatch).
_SOURCE_NEW = "source IN ('hcdinamo', 'hockeyby')"
_SOURCE_OLD = "source IN ('hcdinamo')"

# SELECT * в представлении фиксирует столбцы на момент создания: новый столбец hockey_matches,
# нужный игре, — пересоздать представление в той же миграции.
_VIEW = "CREATE VIEW kk_matches AS SELECT * FROM hockey_matches WHERE source = 'hcdinamo'"


def upgrade() -> None:
    op.drop_constraint("ck_hockey_matches_source", "hockey_matches", type_="check")
    op.create_check_constraint("ck_hockey_matches_source", "hockey_matches", _SOURCE_NEW)
    op.add_column("hockey_matches", sa.Column("league", sa.String(16), nullable=False, server_default="khl"))
    op.create_check_constraint("ck_hockey_matches_league", "hockey_matches", "league IN ('khl', 'extraliga')")
    op.add_column("hockey_matches", sa.Column("home_club_id", sa.String(16), nullable=True))
    op.add_column("hockey_matches", sa.Column("away_club_id", sa.String(16), nullable=True))
    op.add_column("hockey_matches", sa.Column("arena", sa.Text(), nullable=True))
    op.add_column("hockey_matches", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("hockey_matches", sa.Column("tickets_url", sa.Text(), nullable=True))
    op.add_column("hockey_matches", sa.Column("details", postgresql.JSONB(), nullable=True))
    op.add_column("hockey_matches", sa.Column("details_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_hockey_matches_league_starts", "hockey_matches", ["league", "starts_at"])

    op.create_table(
        "hockey_standings",
        sa.Column("league", sa.String(16), primary_key=True),
        sa.Column("team", sa.String(64), primary_key=True),
        sa.Column("place", sa.Integer(), nullable=False),
        sa.Column("games", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("league IN ('khl', 'extraliga')", name="ck_hockey_standings_league"),
    )

    op.execute(_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS kk_matches")
    op.drop_table("hockey_standings")
    op.drop_index("ix_hockey_matches_league_starts", table_name="hockey_matches")
    op.execute("DELETE FROM hockey_matches WHERE source = 'hockeyby'")
    for column in ("details_checked_at", "details", "tickets_url", "city", "arena", "away_club_id", "home_club_id"):
        op.drop_column("hockey_matches", column)
    op.drop_constraint("ck_hockey_matches_league", "hockey_matches", type_="check")
    op.drop_column("hockey_matches", "league")
    op.drop_constraint("ck_hockey_matches_source", "hockey_matches", type_="check")
    op.create_check_constraint("ck_hockey_matches_source", "hockey_matches", _SOURCE_OLD)
