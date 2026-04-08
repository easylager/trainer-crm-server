"""
Widen tier_kind / price_tier_kind for multi-code tariffs (e.g. two_children, adult_and_child).

Revision ID: 0081
Revises: 0080
"""
from alembic import op
import sqlalchemy as sa


revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "trainer_service_price_variants",
        "tier_kind",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=False,
        server_default="adult",
    )
    op.alter_column(
        "bookings",
        "price_tier_kind",
        existing_type=sa.String(length=16),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "bookings",
        "price_tier_kind",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=True,
    )
    op.alter_column(
        "trainer_service_price_variants",
        "tier_kind",
        existing_type=sa.String(length=32),
        type_=sa.String(length=16),
        existing_nullable=False,
        server_default="adult",
    )
