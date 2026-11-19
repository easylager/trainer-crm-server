"""«Кто кого»: откуда создана лига — метка входа (TASK-431).

Revision ID: 0332_kk_league_src
Revises: 0331_kk_league_gestures
Create Date: 2026-11-18

Только добавление: ``hockey_leagues.src`` (nullable, до 16 символов) — метка входа, с которого лига создана в один тап
(``lg1``/``lg2``/``lg3`` — недели еженедельного приглашения). Как ``hockey_players.first_src``: пишется при создании
и больше не меняется; у прежних лиг и созданных из формы «Новая лига» — ``NULL``. Ключа игрока здесь нового нет:
у лиги он и так есть (владелец).

Откат убирает колонку: метка — только для отчёта по входам.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0332_kk_league_src"
down_revision = "0331_kk_league_gestures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hockey_leagues", sa.Column("src", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("hockey_leagues", "src")
