"""Add price per service: trainer sets price in BYN (stored as price_cents).

Revision ID: 0024_trainer_service_prices
Revises: 0023_trainer_arenas
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_trainer_service_prices"
down_revision = "0023_trainer_arenas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_services",
        sa.Column("price_cents", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_services", "price_cents")
