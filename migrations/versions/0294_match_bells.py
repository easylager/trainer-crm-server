"""Матчи на сайте (TASK-347): колокольчик на матч, пропавшие из календаря и перенесённые матчи.

Одна строка на пару (человек, матч). Кнопка на сайте ведёт в чат бота, ``/start mbell_<матч>`` ставит
строку; повторное нажатие строку не удваивает. Отправка «занимает» сообщение отметкой в самой строке
(``remind_claimed_at`` / ``result_claimed_at``) до отправки, поэтому второй цикл его не повторит.
``known_starts_at`` — время, о котором человек знает; расхождение с матчем — повод написать «матч перенесён».
``remind_for`` — начало матча, на которое ушло напоминание: перенос матча даёт одно новое.

В ``hockey_matches``: ``missed_runs`` — сколько полных синхронизаций календаря подряд матч не видели (две и
больше — на сайте он скрыт), ``previous_starts_at`` — время до последнего переноса (для JSON-LD).

Revision ID: 0294_match_bells
Revises: 0284_speed_oval_mk_areas
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0294_match_bells"
down_revision = "0284_speed_oval_mk_areas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hockey_matches", sa.Column("missed_runs", sa.SmallInteger(), server_default="0", nullable=False))
    op.add_column("hockey_matches", sa.Column("previous_starts_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "hockey_match_bells",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("match_id", sa.BigInteger(), sa.ForeignKey("hockey_matches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("known_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remind_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remind_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remind_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("telegram_id", "match_id", name="pk_hockey_match_bells"),
    )
    op.create_index("ix_hockey_match_bells_match", "hockey_match_bells", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_hockey_match_bells_match", table_name="hockey_match_bells")
    op.drop_table("hockey_match_bells")
    op.drop_column("hockey_matches", "previous_starts_at")
    op.drop_column("hockey_matches", "missed_runs")
