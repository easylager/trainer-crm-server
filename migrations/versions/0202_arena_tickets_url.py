"""arena_profiles.tickets_url — external MK checkout (Zamok / Korona Ticket).

Revision ID: 0202_arena_tickets_url
Revises: 0201_merge_interest_share
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0202_arena_tickets_url"
down_revision = "0201_merge_interest_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arena_profiles",
        sa.Column("tickets_url", sa.String(length=512), nullable=True),
    )
    op.execute(
        "UPDATE arena_profiles SET tickets_url = 'https://koronaticket.by/rink' "
        "WHERE slug = 'zamok' AND tickets_url IS NULL"
    )


def downgrade() -> None:
    op.drop_column("arena_profiles", "tickets_url")
