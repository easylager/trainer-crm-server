"""Default subscription prices: CRM 20 BYN/mo, each module 5 BYN/mo (constructor + legacy rows).

Revision ID: 0094_subscription_default_prices
Revises: 0093_trial_full_modules_backfill

Stored amounts are price_cents (1 BYN = 100): 20 BYN = 2000, 5 BYN = 500.
Longer periods: same discount pattern as 0069 (3m: x3 x0.9, 12m: x12 x0.8).
"""
from alembic import op

revision = "0094_subscription_default_prices"
down_revision = "0093_trial_full_modules_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy single-row display on subscription_tier_pricing (monthly anchor)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET price_cents = 2000, updated_at = NOW()
        WHERE tier = 'crm'
    """)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET price_cents = 2500, updated_at = NOW()
        WHERE tier = 'online'
    """)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET price_cents = 3000, updated_at = NOW()
        WHERE tier = 'analytics'
    """)

    # CRM base per period
    op.execute("""
        UPDATE subscription_tier_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 2000
            WHEN 3 THEN ROUND(2000::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(2000::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE tier = 'crm'
    """)

    # Legacy bundle rows (online = crm+online module, analytics = crm+online+analytics)
    op.execute("""
        UPDATE subscription_tier_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 2500
            WHEN 3 THEN ROUND(2500::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(2500::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE tier = 'online'
    """)
    op.execute("""
        UPDATE subscription_tier_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 3000
            WHEN 3 THEN ROUND(3000::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(3000::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE tier = 'analytics'
    """)

    # Module surcharges (constructor)
    op.execute("""
        UPDATE subscription_module_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 500
            WHEN 3 THEN ROUND(500::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(500::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE module IN ('online', 'analytics', 'groups')
    """)


def downgrade() -> None:
    pass
