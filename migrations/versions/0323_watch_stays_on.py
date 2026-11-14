"""Подписка на расписание катка не гаснет после первого сообщения.

Запоминаем сеансы, о которых человек уже знает (``known_sessions``). Следующий проход
пишет только про новые и про снятые, и подписку не выключает.

Revision ID: 0323_watch_stays_on
Revises: 0322_recurring_detach_cleanup
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0323_watch_stays_on"
down_revision = "0322_recurring_detach_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_ice_watches",
        sa.Column("known_sessions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_ice_watches", "known_sessions")
