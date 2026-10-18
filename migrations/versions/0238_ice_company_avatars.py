"""Аватарки откликнувшихся в Telegram для плаката компании.

Revision ID: 0238_ice_company_avatars
Revises: 0237_ice_companies
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0238_ice_company_avatars"
down_revision = "0237_ice_companies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ice_company_responses",
        sa.Column("avatar_file_key", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ice_company_responses", "avatar_file_key")
