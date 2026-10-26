"""Игра «Кто кого», волна 2: ×2 на матч месяца, напоминания и итоги в бот (TASK-335).

Revision ID: 0271_hockey_double_and_reminders
Revises: 0270_hockey_races
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0271_hockey_double_and_reminders"
down_revision = "0270_hockey_races"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Очки хода остаются «базовыми» (0…50) — по ним видно «в точку»; ×2 умножает их в суммах.
    op.add_column("hockey_picks", sa.Column("doubled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("hockey_player_prefs", sa.Column("remind", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "hockey_notices",
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("match_id", sa.Integer(), sa.ForeignKey("hockey_matches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('before', 'result')", name="ck_hockey_notices_kind"),
    )


def downgrade() -> None:
    op.drop_table("hockey_notices")
    op.drop_column("hockey_player_prefs", "remind")
    op.drop_column("hockey_picks", "doubled")
