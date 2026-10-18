"""Матчи Динамо-Минск для игры «Кто кого»: календарь и официальный итог (TASK-296).

Revision ID: 0244_hockey_matches
Revises: 0243_city_picks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0244_hockey_matches"
down_revision = "0243_city_picks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_match_id", sa.String(32), nullable=False),
        sa.Column("home_team", sa.String(64), nullable=False),
        sa.Column("away_team", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="scheduled"),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("decided_in", sa.String(16), nullable=True),
        sa.Column("result_source", sa.String(16), nullable=True),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("review_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_match_id", name="uq_hockey_matches_source_id"),
        sa.CheckConstraint("source IN ('hcdinamo')", name="ck_hockey_matches_source"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'final', 'review', 'cancelled')",
            name="ck_hockey_matches_status",
        ),
        sa.CheckConstraint(
            "decided_in IS NULL OR decided_in IN ('regulation', 'ot', 'so')",
            name="ck_hockey_matches_decided_in",
        ),
        sa.CheckConstraint(
            "result_source IS NULL OR result_source IN ('auto', 'manual')",
            name="ck_hockey_matches_result_source",
        ),
        sa.CheckConstraint(
            "status <> 'final' OR (home_score IS NOT NULL AND away_score IS NOT NULL"
            " AND home_score <> away_score AND decided_in IS NOT NULL AND result_source IS NOT NULL)",
            name="ck_hockey_matches_final_result",
        ),
    )
    op.create_index("ix_hockey_matches_status_starts", "hockey_matches", ["status", "starts_at"])


def downgrade() -> None:
    op.drop_index("ix_hockey_matches_status_starts", table_name="hockey_matches")
    op.drop_table("hockey_matches")
