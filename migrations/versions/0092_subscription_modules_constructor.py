"""CRM base + independent modules (online, analytics, groups) on trainer_subscriptions.

Revision ID: 0092_subscription_modules
Revises: 0091
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0092_subscription_modules"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_subscriptions",
        sa.Column(
            "modules",
            JSONB,
            nullable=False,
            server_default=sa.text(
                "(jsonb_build_object('online', false, 'analytics', false, 'groups', false))"
            ),
        ),
    )

    # Legacy tier → canonical tier 'crm' + modules (analytics tier kept online+analytics per legacy bundle)
    op.execute("""
        UPDATE trainer_subscriptions
        SET
          tier = 'crm',
          modules = CASE tier::text
            WHEN 'crm' THEN '{"online": false, "analytics": false, "groups": false}'::jsonb
            WHEN 'online' THEN '{"online": true, "analytics": false, "groups": false}'::jsonb
            WHEN 'analytics' THEN '{"online": true, "analytics": true, "groups": false}'::jsonb
            ELSE modules
          END
        WHERE tier IS NOT NULL
    """)

    op.create_table(
        "subscription_module_period_pricing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("period_months", sa.SmallInteger(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), server_default="BYN", nullable=False),
        sa.Column("name_ru", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("period_months IN (1, 3, 12)", name="ck_sub_mod_period_months"),
        sa.CheckConstraint("price_cents >= 0", name="ck_sub_mod_price_nonneg"),
        sa.CheckConstraint("period_days > 0", name="ck_sub_mod_period_days_pos"),
        sa.CheckConstraint(
            "module IN ('online', 'analytics', 'groups')",
            name="ck_sub_mod_code",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module", "period_months", name="uq_subscription_module_period"),
    )
    op.create_index("ix_subscription_module_period_pricing_module", "subscription_module_period_pricing", ["module"])

    # Module surcharges = difference between legacy stacked tier prices (same period).
    op.execute("""
        INSERT INTO subscription_module_period_pricing (module, period_months, price_cents, period_days, currency, name_ru)
        SELECT
            'online',
            c.period_months,
            GREATEST(0, o.price_cents - c.price_cents),
            c.period_days,
            (SELECT currency FROM subscription_tier_pricing WHERE tier = 'crm' LIMIT 1),
            'Онлайн-запись в каталоге'
        FROM subscription_tier_period_pricing c
        INNER JOIN subscription_tier_period_pricing o
            ON o.period_months = c.period_months AND o.tier = 'online'
        WHERE c.tier = 'crm'
    """)
    op.execute("""
        INSERT INTO subscription_module_period_pricing (module, period_months, price_cents, period_days, currency, name_ru)
        SELECT
            'analytics',
            o.period_months,
            GREATEST(0, a.price_cents - o.price_cents),
            o.period_days,
            (SELECT currency FROM subscription_tier_pricing WHERE tier = 'crm' LIMIT 1),
            'Аналитика и отчёты'
        FROM subscription_tier_period_pricing o
        INNER JOIN subscription_tier_period_pricing a
            ON a.period_months = o.period_months AND a.tier = 'analytics'
        WHERE o.tier = 'online'
    """)
    # Groups: default surcharge ≈ online module (can be edited in DB later / admin phase)
    op.execute("""
        INSERT INTO subscription_module_period_pricing (module, period_months, price_cents, period_days, currency, name_ru)
        SELECT 'groups', m.period_months, m.price_cents, m.period_days, m.currency, 'Группы (когорты)'
        FROM subscription_module_period_pricing m
        WHERE m.module = 'online'
    """)


def downgrade() -> None:
    op.drop_index("ix_subscription_module_period_pricing_module", table_name="subscription_module_period_pricing")
    op.drop_table("subscription_module_period_pricing")
    op.drop_column("trainer_subscriptions", "modules")
