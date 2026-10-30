"""ice_sessions.hall и ice_sessions.price_tiers.

hall — зал катка («Главная арена» / «Тренировочная арена»).
price_tiers — тарифы, которые не ложатся в взрослый/детский/прокат: семейные комбинации
(«1 взрослый + 1 ребёнок» — 14 BYN). jsonb-список {"label": str, "minor": int}.

Раньше зал СДЮШОР / Юность лежал в session_label и подменял название сеанса («Трен.»).

Revision ID: 0283_ice_session_hall_tiers
Revises: 0282_figure_family_kinds
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0283_ice_session_hall_tiers"
down_revision = "0282_figure_family_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ice_sessions", sa.Column("hall", sa.String(64), nullable=True))
    op.add_column("ice_sessions", sa.Column("price_tiers", postgresql.JSONB(), nullable=True))
    # Старые строки: зал из подписи переносим в hall полным названием, подпись очищаем.
    op.execute(
        """
        UPDATE ice_sessions
           SET hall = CASE WHEN lower(rtrim(trim(session_label), '.')) = 'трен' THEN 'Тренировочная арена'
                           ELSE 'Главная арена' END,
               session_label = NULL
         WHERE lower(rtrim(trim(session_label), '.')) IN ('трен', 'главная')
        """
    )


def downgrade() -> None:
    op.drop_column("ice_sessions", "price_tiers")
    op.drop_column("ice_sessions", "hall")
