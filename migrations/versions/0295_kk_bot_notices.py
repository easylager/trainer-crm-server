"""Игра «Кто кого»: бот — четыре повода, отключение по типу, «болею за», метки мест, письма о продлении (TASK-334 S6).

Revision ID: 0295_kk_bot_notices
Revises: 0294_match_bells
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0295_kk_bot_notices"
down_revision = "0294_match_bells"
branch_labels = None
depends_on = None

KINDS = ("before", "result", "nomove", "overtook", "mfinal")
OLD_KINDS = ("before", "result")


def _in(kinds: tuple[str, ...]) -> str:
    return "kind IN (" + ", ".join(f"'{k}'" for k in kinds) + ")"


def upgrade() -> None:
    op.add_column("hockey_player_prefs", sa.Column("fav_club", sa.String(64), nullable=True))
    for name in ("nomove", "result", "overtook", "mfinal", "league"):
        op.add_column(
            "hockey_player_prefs",
            sa.Column(f"notify_{name}", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    op.add_column("hockey_player_prefs", sa.Column("bot_blocked_at", sa.DateTime(timezone=True), nullable=True))

    op.alter_column("hockey_notices", "kind", existing_type=sa.String(8), type_=sa.String(12))
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(KINDS))
    # Бюджет дня считается по отправленным: быстро найти отправленное игроку за сутки.
    op.create_index("ix_hockey_notices_player_sent", "hockey_notices", ["player_key", "sent_at"])

    # Последнее известное место в лиге: «тебя обошли» — это место стало хуже, чем было.
    op.create_table(
        "hockey_rank_marks",
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # «Лига продлена»: по письму на участника новой лиги; уходит циклом, повтор тика не дублирует.
    op.create_table(
        "hockey_league_notices",
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("hockey_leagues.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("kind", sa.String(12), primary_key=True, server_default="extended"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("hockey_league_notices")
    op.drop_table("hockey_rank_marks")
    op.drop_index("ix_hockey_notices_player_sent", table_name="hockey_notices")
    op.execute("DELETE FROM hockey_notices WHERE kind NOT IN ('before', 'result')")
    op.drop_constraint("ck_hockey_notices_kind", "hockey_notices", type_="check")
    op.create_check_constraint("ck_hockey_notices_kind", "hockey_notices", _in(OLD_KINDS))
    op.alter_column("hockey_notices", "kind", existing_type=sa.String(12), type_=sa.String(8))
    op.drop_column("hockey_player_prefs", "bot_blocked_at")
    for name in ("league", "mfinal", "overtook", "result", "nomove"):
        op.drop_column("hockey_player_prefs", f"notify_{name}")
    op.drop_column("hockey_player_prefs", "fav_club")
