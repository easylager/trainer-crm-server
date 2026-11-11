"""Отметка доступности источника матчей: когда hockey.by последний раз ответил и когда не ответил (TASK-364).

Сайт по ней решает, показывать ли на странице сыгранного матча Экстралиги заглушку «Статистика матча
временно недоступна» вместо пустого места. Одна строка на источник, пишет цикл Экстралиги.

Revision ID: 0319_hockey_source_status
Revises: 0318_kk_league_identity
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0319_hockey_source_status"
down_revision = "0318_kk_league_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hockey_source_status",
        sa.Column("source", sa.String(16), primary_key=True),
        sa.Column("ok_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("hockey_source_status")
