"""Игра «Кто кого»: лига = набор команд + срок, «Продлить» (TASK-334 S3, PDEC-031).

Существующие лиги становятся «Динамо-Минск, до конца сезона»: так очки участников не меняются от
появления матчей Экстралиги (сверка сумм до/после — в тесте миграции).

Revision ID: 0293_kk_league_terms
Revises: 0292_kk_slices_crowns
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0293_kk_league_terms"
down_revision = "0292_kk_slices_crowns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hockey_leagues", sa.Column("scope", sa.String(12), nullable=False, server_default="dinamo"))
    op.add_column(
        "hockey_leagues",
        sa.Column("clubs", postgresql.ARRAY(sa.String(64)), nullable=False, server_default="{}"),
    )
    op.add_column("hockey_leagues", sa.Column("term_kind", sa.String(12), nullable=False, server_default="season"))
    op.add_column("hockey_leagues", sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hockey_leagues", sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "hockey_leagues",
        sa.Column("extended_from", sa.BigInteger(), sa.ForeignKey("hockey_leagues.id", ondelete="SET NULL")),
    )
    # Сезон — с 1 августа по Минску: старт = август сезона, в котором создана лига, конец = следующее 1 августа.
    op.execute("""
        UPDATE hockey_leagues SET
            starts_at = make_timestamptz(
                CASE WHEN EXTRACT(MONTH FROM created_at AT TIME ZONE 'Europe/Minsk') >= 8
                     THEN EXTRACT(YEAR FROM created_at AT TIME ZONE 'Europe/Minsk')::int
                     ELSE EXTRACT(YEAR FROM created_at AT TIME ZONE 'Europe/Minsk')::int - 1 END,
                8, 1, 0, 0, 0, 'Europe/Minsk')
        """)
    op.execute("UPDATE hockey_leagues SET ends_at = starts_at + INTERVAL '1 year'")
    op.alter_column("hockey_leagues", "starts_at", nullable=False)
    op.alter_column("hockey_leagues", "ends_at", nullable=False)
    op.create_check_constraint(
        "ck_hockey_leagues_scope", "hockey_leagues", "scope IN ('all', 'extraliga', 'dinamo', 'clubs')"
    )
    op.create_check_constraint(
        "ck_hockey_leagues_term",
        "hockey_leagues",
        "term_kind IN ('season', 'month', 'weeks4', 'playoff', 'dates')",
    )
    op.create_check_constraint("ck_hockey_leagues_window", "hockey_leagues", "ends_at > starts_at")
    op.create_check_constraint(
        "ck_hockey_leagues_clubs", "hockey_leagues", "(scope = 'clubs') = (cardinality(clubs) > 0)"
    )
    op.create_index("uq_hockey_leagues_extended_from", "hockey_leagues", ["extended_from"], unique=True,
                    postgresql_where=sa.text("extended_from IS NOT NULL"))
    # Старый одноклубный столбец (0270) заменён набором команд.
    op.drop_column("hockey_leagues", "club")


def downgrade() -> None:
    op.add_column(
        "hockey_leagues",
        sa.Column("club", sa.String(64), nullable=False, server_default="Динамо-Минск"),
    )
    op.drop_index("uq_hockey_leagues_extended_from", table_name="hockey_leagues")
    for name in ("ck_hockey_leagues_clubs", "ck_hockey_leagues_window", "ck_hockey_leagues_term", "ck_hockey_leagues_scope"):
        op.drop_constraint(name, "hockey_leagues", type_="check")
    for column in ("extended_from", "ends_at", "starts_at", "term_kind", "clubs", "scope"):
        op.drop_column("hockey_leagues", column)
