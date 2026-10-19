"""Игра «Кто кого»: события карточек в чате — отправили, открыли, вступили (TASK-300).

Revision ID: 0248_hockey_card_events
Revises: 0247_hockey_result_seen
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0248_hockey_card_events"
down_revision = "0247_hockey_result_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Без ключа игрока: воронке хватает счётчиков. league_id без FK — история переживает удаление лиги.
    op.create_table(
        "hockey_card_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("card", sa.String(8), nullable=False),
        sa.Column("league_id", sa.BigInteger(), nullable=True),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("prepared", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('shared', 'opened', 'joined')", name="ck_hockey_card_events_kind"),
        sa.CheckConstraint("card IN ('result', 'league')", name="ck_hockey_card_events_card"),
    )
    op.create_index("ix_hockey_card_events_created", "hockey_card_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_hockey_card_events_created", table_name="hockey_card_events")
    op.drop_table("hockey_card_events")
