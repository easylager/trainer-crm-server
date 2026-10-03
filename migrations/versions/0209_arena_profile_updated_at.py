"""Когда карточку места правили последний раз (TASK-146, Q-012).

У магазина и зала нет владельца с аккаунтом и нет расписания с сайта — значит, нет и
события, по которому можно честно сказать «данные свежие». Теперь оно есть: любая
правка карточки в админке ставит ``updated_at``. Существующим карточкам дату не
выдумываем — NULL означает «неизвестно», и интерфейс тогда молчит о свежести.

Revision ID: 0209_profile_updated_at
Revises: 0208_shops_place_shares
"""

import sqlalchemy as sa
from alembic import op

revision = "0209_profile_updated_at"
down_revision = "0208_shops_place_shares"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("arena_profiles", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("arena_profiles", "updated_at")
