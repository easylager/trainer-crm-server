"""Игра «Кто кого»: сообщения бота включены по умолчанию (решение координатора, TASK-334 S6).

Revision ID: 0297_kk_bot_default_on
Revises: 0295_kk_bot_notices
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0297_kk_bot_default_on"
down_revision = "0295_kk_bot_notices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("hockey_player_prefs", "remind", server_default=sa.true())
    # Существующие строки не трогаем: кто выключил напоминания, того обратно не включаем.


def downgrade() -> None:
    op.alter_column("hockey_player_prefs", "remind", server_default=sa.false())
