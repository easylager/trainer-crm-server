"""Игра «Кто кого»: очки как в прогнозах FIFA — 0, 10, 20, 30, 50 (владелец, 2026-10-19).

Старые очки (0/1/5) снимаются: следующий проход score_finished_matches пересчитает
сыгранные матчи по новым правилам — он берёт ходы без scored_at.

Revision ID: 0250_hockey_fifa_points
Revises: 0249_hockey_card_events
"""

from __future__ import annotations

from alembic import op

revision = "0250_hockey_fifa_points"
down_revision = "0249_hockey_card_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_hockey_picks_points", "hockey_picks", type_="check")
    op.execute("UPDATE hockey_picks SET points = NULL, scored_at = NULL WHERE points IS NOT NULL")
    op.create_check_constraint(
        "ck_hockey_picks_points", "hockey_picks", "points IS NULL OR points IN (0, 10, 20, 30, 50)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_hockey_picks_points", "hockey_picks", type_="check")
    op.execute("UPDATE hockey_picks SET points = NULL, scored_at = NULL WHERE points IS NOT NULL")
    op.create_check_constraint("ck_hockey_picks_points", "hockey_picks", "points IS NULL OR points IN (0, 1, 5)")
