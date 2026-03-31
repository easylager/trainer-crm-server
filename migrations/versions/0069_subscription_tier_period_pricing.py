"""Per-tier period pricing matrix (1 / 3 / 12 months).

Revision ID: 0069_tier_period_pricing
Revises: 0068_subscription_tiers_no_cat
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.dialects.postgresql import JSONB

_subscription_tier_enum = PG_ENUM(
    "crm",
    "online",
    "analytics",
    name="subscription_tier_enum",
    create_type=False,
)

revision = "0069_tier_period_pricing"
down_revision = "0068_subscription_tiers_no_cat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_tier_period_pricing",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tier", _subscription_tier_enum, nullable=False),
        sa.Column("period_months", sa.SmallInteger(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("period_months IN (1, 3, 12)", name="ck_subscription_tier_period_months"),
        sa.CheckConstraint("price_cents >= 0", name="ck_subscription_tier_period_price_nonneg"),
        sa.CheckConstraint("period_days > 0", name="ck_subscription_tier_period_days_pos"),
        sa.ForeignKeyConstraint(["tier"], ["subscription_tier_pricing.tier"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tier", "period_months", name="uq_subscription_tier_period"),
    )
    op.create_index("ix_subscription_tier_period_pricing_tier", "subscription_tier_period_pricing", ["tier"])

    op.create_table(
        "subscription_tier_period_pricing_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tier_period_pricing_id", sa.Integer(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_fields", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tier_period_pricing_id"],
            ["subscription_tier_period_pricing.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sub_tier_period_pricing_audit_row",
        "subscription_tier_period_pricing_audit",
        ["tier_period_pricing_id"],
    )

    # Seed from legacy monthly row: 1m = current price; 3m/12m = same bundle rules as old trainer UI (10% / 20%).
    op.execute("""
        INSERT INTO subscription_tier_period_pricing (tier, period_months, price_cents, period_days)
        SELECT tier, 1, price_cents, 30 FROM subscription_tier_pricing
    """)
    op.execute("""
        INSERT INTO subscription_tier_period_pricing (tier, period_months, price_cents, period_days)
        SELECT tier, 3, ROUND(price_cents::numeric * 3 * 0.9)::integer, 90 FROM subscription_tier_pricing
    """)
    op.execute("""
        INSERT INTO subscription_tier_period_pricing (tier, period_months, price_cents, period_days)
        SELECT tier, 12, ROUND(price_cents::numeric * 12 * 0.8)::integer, 365 FROM subscription_tier_pricing
    """)


def downgrade() -> None:
    op.drop_table("subscription_tier_period_pricing_audit")
    op.drop_table("subscription_tier_period_pricing")
