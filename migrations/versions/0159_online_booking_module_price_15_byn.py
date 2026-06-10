"""Set online booking module default price to 15 BYN/month.

Revision ID: 0159_online_booking_price
Revises: 0158_services_platform_meta

CRM base stays 20 BYN/month. The online module becomes +15 BYN/month,
so legacy display bundles become:
- online: CRM + online = 35 BYN/month
- analytics: CRM + online + analytics = 40 BYN/month
"""
from alembic import op


revision = "0159_online_booking_price"
down_revision = "0158_services_platform_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy monthly anchors shown in admin / backward-compatible tier cards.
    op.execute("""
        UPDATE subscription_tier_pricing
        SET price_cents = 3500, updated_at = NOW()
        WHERE tier = 'online'
    """)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET price_cents = 4000, updated_at = NOW()
        WHERE tier = 'analytics'
    """)

    # Legacy bundle period prices.
    op.execute("""
        UPDATE subscription_tier_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 3500
            WHEN 3 THEN ROUND(3500::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(3500::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE tier = 'online'
    """)
    op.execute("""
        UPDATE subscription_tier_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 4000
            WHEN 3 THEN ROUND(4000::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(4000::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE tier = 'analytics'
    """)

    # Constructor module price: online booking only. Analytics and groups remain unchanged.
    op.execute("""
        UPDATE subscription_module_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 1500
            WHEN 3 THEN ROUND(1500::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(1500::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE module = 'online'
    """)


def downgrade() -> None:
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
    op.execute("""
        UPDATE subscription_module_period_pricing
        SET price_cents = CASE period_months
            WHEN 1 THEN 500
            WHEN 3 THEN ROUND(500::numeric * 3 * 0.9)::integer
            WHEN 12 THEN ROUND(500::numeric * 12 * 0.8)::integer
        END, updated_at = NOW()
        WHERE module = 'online'
    """)
