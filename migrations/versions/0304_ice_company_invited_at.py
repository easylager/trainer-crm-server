"""Mark companies whose card was handed to the organizer.

A reply on a match page silently creates a company; only an invite makes
the page say "the card is in the chat".

Revision ID: 0304_ice_company_invited_at
Revises: 0303_kk_moved_notice
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0304_ice_company_invited_at"
down_revision = "0303_kk_moved_notice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ice_companies", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("ice_companies", "invited_at")
