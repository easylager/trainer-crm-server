"""trainer_subscriptions: billing_period_months for tier checkout UX.

Revision ID: 0070_trainer_sub_billing_months
Revises: 0069_tier_period_pricing
"""
from alembic import op
import sqlalchemy as sa

revision = "0070_trainer_sub_billing_months"
down_revision = "0069_tier_period_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_subscriptions",
        sa.Column("billing_period_months", sa.SmallInteger(), nullable=True),
    )
    op.create_check_constraint(
        "ck_trainer_sub_billing_period_months",
        "trainer_subscriptions",
        "billing_period_months IS NULL OR billing_period_months IN (1, 3, 12)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trainer_sub_billing_period_months", "trainer_subscriptions", type_="check")
    op.drop_column("trainer_subscriptions", "billing_period_months")
