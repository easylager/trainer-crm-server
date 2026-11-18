"""«Кто кого»: публичный идентификатор игрока для чужого стенда (TASK-430).

Revision ID: 0330_kk_player_public_id
Revises: 0329_warm_visitors
Create Date: 2026-11-18

Только добавление: ``hockey_players.public_id`` — случайные 12 символов, уникальные, по умолчанию ставятся на
вставке (поэтому четыре места, создающие игрока, менять не нужно). ``player_key`` — Telegram-id, наружу он не
уходит; в таблицах и на чужом стенде игрока называет ``public_id``. Существующие строки получают значение при
добавлении колонки (волатильный DEFAULT считается для каждой строки отдельно).

Откат убирает колонку: идентификатор производный, данных он не хранит.
"""
from __future__ import annotations

from alembic import op

revision = "0330_kk_player_public_id"
down_revision = "0329_warm_visitors"
branch_labels = None
depends_on = None

_DEFAULT = "substr(md5(random()::text || clock_timestamp()::text), 1, 12)"


def upgrade() -> None:
    op.execute(f"ALTER TABLE hockey_players ADD COLUMN IF NOT EXISTS public_id VARCHAR(16) NOT NULL DEFAULT {_DEFAULT}")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_hockey_players_public_id ON hockey_players (public_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_hockey_players_public_id")
    op.execute("ALTER TABLE hockey_players DROP COLUMN IF EXISTS public_id")
