"""ice_city_interest: Ice tab «скоро добавим» client taps.

Revision ID: 0199_ice_city_interest
Revises: 0198_ice_scrape_runs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0199_ice_city_interest"
down_revision = "0198_ice_scrape_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_city_interest",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "city_id",
            sa.Integer(),
            sa.ForeignKey("cities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("intent", sa.String(length=16), nullable=False, server_default="skate"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="coming_soon_cta"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ice_city_interest_city_id", "ice_city_interest", ["city_id"])


def downgrade() -> None:
    op.drop_index("ix_ice_city_interest_city_id", table_name="ice_city_interest")
    op.drop_table("ice_city_interest")
