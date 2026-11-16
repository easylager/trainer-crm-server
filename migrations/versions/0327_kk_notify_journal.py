"""«Кто кого»: журнал решений уведомлений, пауза игрока, учёт недельных прогонов (TASK-426, срез 0).

Revision ID: 0327_kk_notify_journal
Revises: 0326_scrub_ops_blurb_2
Create Date: 2026-11-16

Только добавления: две новые таблицы и одна nullable-колонка. Существующие строки и ограничения не меняются.

* ``kk_notify_decisions`` — по записи на игрока и проход: фаза, выбранный повод или причина отказа, результат.
  Внешнего ключа на игрока нет намеренно: журнал не должен исчезать вслед за игроком и не тянет его данные.
  Кроме ``player_key`` личного в таблице ничего нет.
* ``kk_notify_runs`` — «занято» для разовых задач периода (недельный отчёт админу): один раз на период.
* ``hockey_player_prefs.notify_paused_until`` — пауза приглашений («два приглашения подряд без хода — на месяц»).
"""

import sqlalchemy as sa
from alembic import op

revision = "0327_kk_notify_journal"
down_revision = "0326_scrub_ops_blurb_2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kk_notify_decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tick_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("player_key", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(12), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("decision", sa.String(12), nullable=False),
        sa.Column("reason", sa.String(48), nullable=True),
        sa.Column("result", sa.String(12), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("decision IN ('send', 'skip', 'dry_run', 'error')", name="ck_kk_notify_decisions_decision"),
    )
    op.create_index("ix_kk_notify_decisions_player", "kk_notify_decisions", ["player_key", "tick_at"])
    op.create_index("ix_kk_notify_decisions_tick", "kk_notify_decisions", ["tick_at"])

    op.create_table(
        "kk_notify_runs",
        sa.Column("name", sa.String(32), primary_key=True),
        sa.Column("period", sa.String(16), primary_key=True),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column("hockey_player_prefs", sa.Column("notify_paused_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hockey_player_prefs", "notify_paused_until")
    op.drop_table("kk_notify_runs")
    op.drop_index("ix_kk_notify_decisions_tick", table_name="kk_notify_decisions")
    op.drop_index("ix_kk_notify_decisions_player", table_name="kk_notify_decisions")
    op.drop_table("kk_notify_decisions")
