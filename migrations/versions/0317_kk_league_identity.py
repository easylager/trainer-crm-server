"""Игра «Кто кого»: картинка лиги, строка «на что играем» и жалобы на лигу (TASK-361).

Владелец задаёт картинку и строку свободно, без премодерации; защита платформы — жалоба участника
(одно сообщение админам в сутки на лигу) и очистка админом.

Revision ID: 0317_kk_league_identity
Revises: 0316_spb_rink_cards_batch3
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0317_kk_league_identity"
down_revision = "0316_spb_rink_cards_batch3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hockey_leagues", sa.Column("image_key", sa.Text(), nullable=True))
    op.add_column("hockey_leagues", sa.Column("stake_text", sa.String(80), nullable=True))
    op.create_check_constraint(
        "ck_hockey_leagues_stake_text",
        "hockey_leagues",
        "stake_text IS NULL OR char_length(btrim(stake_text)) BETWEEN 1 AND 80",
    )
    op.create_table(
        "hockey_league_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "league_id",
            sa.BigInteger(),
            sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reporter_key", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Когда по этой жалобе ушло сообщение админам. Повторные жалобы за сутки сообщение не дублируют.
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_hockey_league_reports_league_created", "hockey_league_reports", ["league_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_hockey_league_reports_league_created", table_name="hockey_league_reports")
    op.drop_table("hockey_league_reports")
    op.drop_constraint("ck_hockey_leagues_stake_text", "hockey_leagues", type_="check")
    op.drop_column("hockey_leagues", "stake_text")
    op.drop_column("hockey_leagues", "image_key")
