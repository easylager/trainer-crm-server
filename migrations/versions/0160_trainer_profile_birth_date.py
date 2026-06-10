"""Add optional birth_date to trainer profiles.

Revision ID: 0160_trainer_birth_date
Revises: 0159_online_booking_price
"""
from alembic import op
import sqlalchemy as sa


revision = "0160_trainer_birth_date"
down_revision = "0159_online_booking_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trainer_profiles", sa.Column("birth_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("trainer_profiles", "birth_date")
