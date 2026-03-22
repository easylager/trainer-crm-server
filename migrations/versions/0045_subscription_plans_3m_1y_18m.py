"""Add subscription plans: 3 months, 1 year, 1.5 years (B2B Belarus).

Revision ID: 0045_plans_3m_1y
Revises: 0044_drop_passes
"""
from alembic import op


revision = "0045_plans_3m_1y"
down_revision = "0044_drop_passes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
        VALUES
            ('3 месяца', 7900, 90, false, 2),
            ('Год', 29900, 365, false, 3),
            ('1,5 года', 39900, 548, false, 4)
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM subscription_plans
        WHERE name IN ('3 месяца', 'Год', '1,5 года')
    """)
