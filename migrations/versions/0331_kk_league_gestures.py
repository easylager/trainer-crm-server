"""«Кто кого»: жесты в вечере лиги — «Стук клюшкой» и «2 минуты» (TASK-431).

Revision ID: 0331_kk_league_gestures
Revises: 0330_kk_player_public_id
Create Date: 2026-11-18

Только добавление: ``hockey_league_gestures`` — один жест от человека человеку за игровой день в лиге
(ключ ``league_id, day, from_key, to_key``), себе нельзя (CHECK). Жест можно сменить или снять — строка
перезаписывается или удаляется. Лига, игрок ушли из базы — их жесты уходят каскадом.

Откат удаляет таблицу: жесты — шутка вечера, не результат игры.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0331_kk_league_gestures"
down_revision = "0330_kk_player_public_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_league_gestures",
        sa.Column(
            "league_id", sa.BigInteger(), sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column(
            "from_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "to_key", sa.BigInteger(), sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("kind", sa.String(8), nullable=False),
        # Облик жеста (скин): на смысл и счёт не влияет, по умолчанию — базовый.
        sa.Column("skin", sa.String(24), nullable=False, server_default="base"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('stick', 'pen')", name="ck_hockey_league_gestures_kind"),
        sa.CheckConstraint("from_key <> to_key", name="ck_hockey_league_gestures_not_self"),
    )
    op.create_index("ix_hockey_league_gestures_to", "hockey_league_gestures", ["league_id", "to_key", "day"])


def downgrade() -> None:
    op.drop_index("ix_hockey_league_gestures_to", table_name="hockey_league_gestures")
    op.drop_table("hockey_league_gestures")
