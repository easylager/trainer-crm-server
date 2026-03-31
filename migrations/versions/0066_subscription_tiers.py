"""Subscription tiers: crm, online, analytics with nested access model.

Adds subscription_tier_pricing table for admin-editable tier pricing,
and tier column to trainer_subscriptions.

Revision ID: 0066_subscription_tiers
Revises: 0065_trainer_moderation_submitted_at
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB

# PG-only: sa.Enum ignores create_type; must use dialect ENUM so CREATE TABLE skips CREATE TYPE.
_subscription_tier_enum = PG_ENUM(
    "crm",
    "online",
    "analytics",
    name="subscription_tier_enum",
    create_type=False,
)


revision = "0066_subscription_tiers"
down_revision = "0065_trainer_mod_submitted"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enum for subscription tiers (hierarchical: analytics > online > crm).
    # SQLAlchemy's sa.Enum would also emit CREATE TYPE on create_table unless create_type=False;
    # we create the PG type once here and tell Enum to reuse it (avoids DuplicateObject).
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE subscription_tier_enum AS ENUM ('crm', 'online', 'analytics');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$
    """)

    # Pricing table for tiers (admin-editable)
    op.create_table(
        "subscription_tier_pricing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tier", _subscription_tier_enum, nullable=False, unique=True),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), server_default="BYN", nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("name_ru", sa.String(128), nullable=False),
        sa.Column("short_description_ru", sa.Text(), nullable=True),
        sa.Column("bullets_json", JSONB, nullable=True),  # e.g. ["Расписание", "CRM клиентов"]
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_tier_pricing_tier", "subscription_tier_pricing", ["tier"], unique=True)

    # Add tier column to trainer_subscriptions (nullable for existing rows → default none)
    op.add_column(
        "trainer_subscriptions",
        sa.Column("tier", _subscription_tier_enum, nullable=True),
    )

    # Seed default tier pricing (all active, reasonable defaults)
    op.execute("""
        INSERT INTO subscription_tier_pricing (tier, price_cents, currency, period_days, name_ru, short_description_ru, bullets_json, display_order, is_active)
        VALUES
            ('crm', 1900, 'BYN', 30, 'CRM', 'Базовый функционал для работы с клиентами', '["Расписание и шаблоны", "Ручная запись клиентов", "Ведение клиентской базы", "Абонементы и сертификаты"]', 1, true),
            ('online', 2900, 'BYN', 30, 'Онлайн-запись', 'Клиенты записываются сами через каталог', '["Всё из CRM", "Публикация в каталоге", "Самостоятельная запись клиентов", "Уведомления о записях"]', 2, true),
            ('analytics', 4900, 'BYN', 30, 'Аналитика', 'Отчёты и финансовая аналитика', '["Всё из Онлайн-записи", "Статистика записей", "Финансовые отчёты", "Выгрузка данных"]', 3, true)
    """)

    # Migrate existing subscriptions: set tier='online' for all active (backward compat)
    op.execute("""
        UPDATE trainer_subscriptions SET tier = 'online' WHERE tier IS NULL
    """)

    # Audit table for tier pricing changes
    op.create_table(
        "subscription_tier_pricing_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tier_pricing_id", sa.Integer(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_fields", JSONB, nullable=False),  # {"price_cents": {"old": 1900, "new": 2400}}
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tier_pricing_id"], ["subscription_tier_pricing.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_subscription_tier_pricing_audit_tier_pricing_id", "subscription_tier_pricing_audit", ["tier_pricing_id"])


def downgrade() -> None:
    op.drop_table("subscription_tier_pricing_audit")
    op.drop_column("trainer_subscriptions", "tier")
    op.drop_table("subscription_tier_pricing")
    op.execute("DROP TYPE IF EXISTS subscription_tier_enum")
