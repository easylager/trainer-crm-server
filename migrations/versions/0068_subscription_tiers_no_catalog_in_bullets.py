"""Ensure CRM/online bullets never list catalog publication (free feature).

Normalizes CRM to four core bullets. If a DB ran an older 0067 revision that
added «Публикация в каталоге» to CRM, this removes it.

Revision ID: 0068_subscription_tiers_no_cat
Revises: 0067_subscription_tier_bullets
"""
from alembic import op


revision = "0068_subscription_tiers_no_cat"
down_revision = "0067_subscription_tier_bullets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE subscription_tier_pricing
        SET bullets_json = '["Расписание и шаблоны", "Ручная запись клиентов", "Ведение клиентской базы", "Абонементы и сертификаты"]'::jsonb,
            updated_at = now()
        WHERE tier = 'crm'
    """)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET bullets_json = '["Всё из CRM", "Самостоятельная запись клиентов", "Уведомления о записях"]'::jsonb,
            updated_at = now()
        WHERE tier = 'online'
    """)


def downgrade() -> None:
    # Restore 0066-style online bullets (includes publication line — product may prefer re-run 0067)
    op.execute("""
        UPDATE subscription_tier_pricing
        SET bullets_json = '["Всё из CRM", "Публикация в каталоге", "Самостоятельная запись клиентов", "Уведомления о записях"]'::jsonb,
            updated_at = now()
        WHERE tier = 'online'
    """)
