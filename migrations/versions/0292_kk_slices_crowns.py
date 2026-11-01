"""Игра «Кто кого», зимняя модель: срезы команда × период, короны, козырь недели (TASK-334, PDEC-031).

- ``game_matches`` — матчи Динамо и Экстралиги для игры (``kk_matches`` остаётся только Динамо:
  на неё завязаны цикл итогов hcdinamo.by и строка на главной);
- ``hockey_picks``: ``picked_at`` (для переноса матча «в прошлое») и ``trump_week`` — козырь ×2 один на
  игрока и неделю пн-вс по Минску (уникальный индекс закрывает гонку двух вкладок);
- ``hockey_races`` теперь период (месяц) без клуба; короны получают клуб/вид/окно; закрытия срезов и
  звания сезона — отдельные таблицы;
- ``hockey_matches``: ``result_probe`` (итог Экстралиги публикуется после двух одинаковых опросов) и
  живой счёт.

Revision ID: 0292_kk_slices_crowns
Revises: 0291_winter_subscriptions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0292_kk_slices_crowns"
down_revision = "0291_winter_subscriptions"
branch_labels = None
depends_on = None

_DINAMO = "Динамо-Минск"


def upgrade() -> None:
    # --- матчи: опрос итога и живой счёт, затем представление для игры ---
    op.add_column("hockey_matches", sa.Column("result_probe", postgresql.JSONB(), nullable=True))
    op.add_column("hockey_matches", sa.Column("live_home_score", sa.Integer(), nullable=True))
    op.add_column("hockey_matches", sa.Column("live_away_score", sa.Integer(), nullable=True))
    op.add_column("hockey_matches", sa.Column("live_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("CREATE VIEW game_matches AS SELECT * FROM hockey_matches")
    # kk_matches замораживает список столбцов при создании — новые столбцы ей не нужны.

    # --- ходы: время хода и козырь недели ---
    op.add_column("hockey_picks", sa.Column("picked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE hockey_picks SET picked_at = updated_at")
    op.alter_column("hockey_picks", "picked_at", nullable=False, server_default=sa.func.now())
    op.add_column("hockey_picks", sa.Column("trump_week", sa.Date(), nullable=True))
    op.execute("""
        UPDATE hockey_picks AS p
        SET trump_week = date_trunc('week', m.starts_at AT TIME ZONE 'Europe/Minsk')::date
        FROM hockey_matches AS m
        WHERE m.id = p.match_id AND p.doubled
        """)
    # Если в старой модели «один в месяц» двух козырей в одной неделе быть не могло; на всякий случай
    # оставляем самый ранний козырь недели, остальные снимаем.
    op.execute("""
        UPDATE hockey_picks AS p SET doubled = false, trump_week = NULL
        WHERE p.trump_week IS NOT NULL AND p.id <> (
            SELECT MIN(x.id) FROM hockey_picks AS x
            WHERE x.player_key = p.player_key AND x.trump_week = p.trump_week)
        """)
    op.create_check_constraint("ck_hockey_picks_trump", "hockey_picks", "doubled = (trump_week IS NOT NULL)")
    op.create_index(
        "uq_hockey_picks_trump_week",
        "hockey_picks",
        ["player_key", "trump_week"],
        unique=True,
        postgresql_where=sa.text("trump_week IS NOT NULL"),
    )

    # --- гонки: период без клуба ---
    op.execute("""
        DELETE FROM hockey_races AS a USING hockey_races AS b
        WHERE a.kind = b.kind AND a.starts_at = b.starts_at AND a.id > b.id
        """)
    op.drop_constraint("uq_hockey_races_club_kind_start", "hockey_races", type_="unique")
    op.add_column("hockey_crowns", sa.Column("club", sa.String(64), nullable=True))
    op.add_column("hockey_crowns", sa.Column("kind", sa.String(16), nullable=False, server_default="month"))
    op.add_column("hockey_crowns", sa.Column("period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hockey_crowns", sa.Column("period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("hockey_crowns", sa.Column("played", sa.Integer(), nullable=False, server_default="0"))
    # Короны старой модели считались по Динамо: клуб проставляем, лиговые — «месяц лиги».
    op.execute(f"""
        UPDATE hockey_crowns AS c
        SET club = '{_DINAMO}',
            kind = CASE WHEN c.league_id IS NULL THEN 'month' ELSE 'league_month' END,
            period_start = r.starts_at, period_end = r.ends_at
        FROM hockey_races AS r WHERE r.id = c.race_id
        """)
    op.alter_column("hockey_races", "club", nullable=True)
    op.execute("UPDATE hockey_races SET club = NULL")
    op.create_unique_constraint("uq_hockey_races_kind_start", "hockey_races", ["kind", "starts_at"])
    op.alter_column("hockey_crowns", "race_id", nullable=True)
    op.alter_column("hockey_crowns", "period_start", nullable=False)
    op.alter_column("hockey_crowns", "period_end", nullable=False)
    op.create_check_constraint(
        "ck_hockey_crowns_kind", "hockey_crowns", "kind IN ('month', 'league_month', 'league_term')"
    )
    op.execute("DROP INDEX IF EXISTS uq_hockey_crowns_race_scope_player")
    op.execute(
        "CREATE UNIQUE INDEX uq_hockey_crowns_slice_player ON hockey_crowns "
        "(kind, period_start, COALESCE(club, ''), COALESCE(league_id, 0), player_key)"
    )

    # --- закрытия срезов (идемпотентность) и звания сезона ---
    op.create_table(
        "hockey_closures",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("club", sa.String(64), nullable=True),
        sa.Column("league_id", sa.BigInteger(), nullable=True),
        sa.Column("crowned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind IN ('month', 'season', 'league_month', 'league_term')", name="ck_hockey_closures_kind"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_hockey_closures_slice ON hockey_closures "
        "(kind, period_start, COALESCE(club, ''), COALESCE(league_id, 0))"
    )
    # Уже закрытые гонки старой модели считаем закрытыми по Динамо.
    op.execute(f"""
        INSERT INTO hockey_closures (kind, period_start, club, closed_at)
        SELECT 'month', starts_at, '{_DINAMO}', closed_at FROM hockey_races WHERE closed_at IS NOT NULL
        """)
    op.create_table(
        "hockey_titles",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("season", sa.String(9), nullable=False),
        sa.Column("club", sa.String(64), nullable=True),
        sa.Column(
            "player_key",
            sa.BigInteger(),
            sa.ForeignKey("hockey_players.player_key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("exact", sa.Integer(), nullable=False),
        sa.Column("played", sa.Integer(), nullable=False),
        sa.Column("awarded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_hockey_titles_slice_player ON hockey_titles " "(season, COALESCE(club, ''), player_key)"
    )


def downgrade() -> None:
    op.drop_table("hockey_titles")
    op.drop_table("hockey_closures")
    op.execute("DROP INDEX IF EXISTS uq_hockey_crowns_slice_player")
    op.drop_constraint("ck_hockey_crowns_kind", "hockey_crowns", type_="check")
    # Короны, которых не было в старой модели (клубные срезы, срок лиги), старая схема не вмещает.
    op.execute(
        f"DELETE FROM hockey_crowns WHERE kind = 'league_term' OR race_id IS NULL "
        f"OR COALESCE(club, '{_DINAMO}') <> '{_DINAMO}'"
    )
    op.alter_column("hockey_crowns", "race_id", nullable=False)
    for column in ("played", "period_end", "period_start", "kind", "club"):
        op.drop_column("hockey_crowns", column)
    op.execute(
        "CREATE UNIQUE INDEX uq_hockey_crowns_race_scope_player "
        "ON hockey_crowns (race_id, COALESCE(league_id, 0), player_key)"
    )
    op.drop_constraint("uq_hockey_races_kind_start", "hockey_races", type_="unique")
    op.execute(f"UPDATE hockey_races SET club = '{_DINAMO}'")
    op.alter_column("hockey_races", "club", nullable=False)
    op.create_unique_constraint("uq_hockey_races_club_kind_start", "hockey_races", ["club", "kind", "starts_at"])
    op.drop_index("uq_hockey_picks_trump_week", table_name="hockey_picks")
    op.drop_constraint("ck_hockey_picks_trump", "hockey_picks", type_="check")
    op.drop_column("hockey_picks", "trump_week")
    op.drop_column("hockey_picks", "picked_at")
    op.execute("DROP VIEW IF EXISTS game_matches")
    for column in ("live_at", "live_away_score", "live_home_score", "result_probe"):
        op.drop_column("hockey_matches", column)
