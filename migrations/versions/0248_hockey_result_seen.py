"""Игра «Кто кого»: игрок открыл итог своего хода (TASK-299).

Revision ID: 0248_hockey_result_seen
Revises: 0247_hockey_leagues
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0248_hockey_result_seen"
down_revision = "0247_hockey_leagues"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hockey_picks", sa.Column("result_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hockey_picks", "result_seen_at")
