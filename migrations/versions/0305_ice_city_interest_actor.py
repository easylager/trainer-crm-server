"""ice_city_interest: remember who asked, so the city launch can notify them.

The row used to carry only the city. With ``telegram_id`` (the client catalog key)
a repeat tap by the same person is one row, and there is somebody to message when
the city gets its first rink. Anonymous taps keep ``telegram_id`` NULL.

Revision ID: 0305_ice_city_interest_actor
Revises: 0304_ice_company_invited_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0305_ice_city_interest_actor"
down_revision = "0304_ice_company_invited_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ice_city_interest", sa.Column("telegram_id", sa.BigInteger(), nullable=True))
    op.create_index(
        "uq_ice_city_interest_person",
        "ice_city_interest",
        ["city_id", "intent", "telegram_id"],
        unique=True,
        postgresql_where=sa.text("telegram_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_ice_city_interest_person", table_name="ice_city_interest")
    op.drop_column("ice_city_interest", "telegram_id")
