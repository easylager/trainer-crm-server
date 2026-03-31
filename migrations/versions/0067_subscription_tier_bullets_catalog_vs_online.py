"""Fix online tier bullets: self-booking + notifications; drop «Публикация в каталоге».

Catalog visibility is a free platform feature — not a paid tier bullet.

Revision ID: 0067_subscription_tier_bullets
Revises: 0066_subscription_tiers
"""
from alembic import op


revision = "0067_subscription_tier_bullets"
down_revision = "0066_subscription_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE subscription_tier_pricing
        SET bullets_json = '["Всё из CRM", "Самостоятельная запись клиентов", "Уведомления о записях"]'::jsonb,
            updated_at = now()
        WHERE tier = 'online'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE subscription_tier_pricing
        SET bullets_json = '["Всё из CRM", "Публикация в каталоге", "Самостоятельная запись клиентов", "Уведомления о записях"]'::jsonb,
            updated_at = now()
        WHERE tier = 'online'
    """)
