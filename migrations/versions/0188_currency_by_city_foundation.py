"""Currency by city + price_group foundation (TASK-043).

Adds ``cities.country`` (BY/RU) — drives display currency (BYN/RUB) — and
``cities.price_group`` (BY_BASE/RU_BASE/...) — drives which row of the subscription
pricing tables applies to a trainer's city. Backfills the two RU cities already seeded
in prod ("Москва/МО", "Санкт-Петербург/ЛО") by name, not id — ids differ between
environments, names are the stable identifier confirmed by the product owner.

The three subscription pricing tables (``subscription_tier_pricing``,
``subscription_tier_period_pricing``, ``subscription_module_period_pricing``) each get
a ``price_group`` column so more than one price row can exist per tier/module — needed
for RU pricing (TASK-044) and the BY small-city discount (TASK-045). Existing unique
constraints are widened to include ``price_group``; all current rows default to
``BY_BASE`` so today's single-row-per-tier behavior is unchanged until a later task
inserts additional rows.

Revision ID: 0188_currency_by_city_foundation
Revises: 0187_arena_trainer_created
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0188_currency_by_city_foundation"
down_revision = "0187_arena_trainer_created"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- cities: country drives currency, price_group drives which pricing row applies ---
    op.add_column(
        "cities",
        sa.Column("country", sa.String(2), server_default="BY", nullable=False),
    )
    op.add_column(
        "cities",
        sa.Column("price_group", sa.String(16), server_default="BY_BASE", nullable=False),
    )
    op.execute("""
        UPDATE cities
        SET country = 'RU', price_group = 'RU_BASE'
        WHERE name IN ('Москва/МО', 'Санкт-Петербург/ЛО')
    """)

    # --- widen tier + period pricing to allow one row per (tier, price_group) ---
    # Order matters: the FK on subscription_tier_period_pricing depends on the unique
    # index being replaced, so it must be dropped before that index/constraint.
    op.add_column(
        "subscription_tier_pricing",
        sa.Column("price_group", sa.String(16), server_default="BY_BASE", nullable=False),
    )
    op.add_column(
        "subscription_tier_period_pricing",
        sa.Column("price_group", sa.String(16), server_default="BY_BASE", nullable=False),
    )
    op.drop_constraint(
        "subscription_tier_period_pricing_tier_fkey", "subscription_tier_period_pricing", type_="foreignkey"
    )
    op.drop_constraint("uq_subscription_tier_period", "subscription_tier_period_pricing", type_="unique")

    op.drop_constraint("subscription_tier_pricing_tier_key", "subscription_tier_pricing", type_="unique")
    op.drop_index("ix_subscription_tier_pricing_tier", table_name="subscription_tier_pricing")
    op.create_unique_constraint(
        "uq_subscription_tier_pricing_tier_group",
        "subscription_tier_pricing",
        ["tier", "price_group"],
    )
    op.create_index(
        "ix_subscription_tier_pricing_tier",
        "subscription_tier_pricing",
        ["tier"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_subscription_tier_period_group",
        "subscription_tier_period_pricing",
        ["tier", "period_months", "price_group"],
    )
    op.create_foreign_key(
        "subscription_tier_period_pricing_tier_fkey",
        "subscription_tier_period_pricing",
        "subscription_tier_pricing",
        ["tier", "price_group"],
        ["tier", "price_group"],
        ondelete="CASCADE",
    )

    # --- subscription_module_period_pricing: same widening, no FK to worry about ---
    op.add_column(
        "subscription_module_period_pricing",
        sa.Column("price_group", sa.String(16), server_default="BY_BASE", nullable=False),
    )
    op.drop_constraint("uq_subscription_module_period", "subscription_module_period_pricing", type_="unique")
    op.create_unique_constraint(
        "uq_subscription_module_period_group",
        "subscription_module_period_pricing",
        ["module", "period_months", "price_group"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_subscription_module_period_group", "subscription_module_period_pricing", type_="unique"
    )
    op.create_unique_constraint(
        "uq_subscription_module_period", "subscription_module_period_pricing", ["module", "period_months"]
    )
    op.drop_column("subscription_module_period_pricing", "price_group")

    # Drop the FK before touching either side's unique constraints (same ordering
    # constraint as upgrade, just in reverse).
    op.drop_constraint(
        "subscription_tier_period_pricing_tier_fkey", "subscription_tier_period_pricing", type_="foreignkey"
    )
    op.drop_constraint("uq_subscription_tier_period_group", "subscription_tier_period_pricing", type_="unique")

    op.drop_index("ix_subscription_tier_pricing_tier", table_name="subscription_tier_pricing")
    op.drop_constraint(
        "uq_subscription_tier_pricing_tier_group", "subscription_tier_pricing", type_="unique"
    )
    op.create_index(
        "ix_subscription_tier_pricing_tier", "subscription_tier_pricing", ["tier"], unique=True
    )
    op.create_unique_constraint(
        "subscription_tier_pricing_tier_key", "subscription_tier_pricing", ["tier"]
    )
    op.drop_column("subscription_tier_pricing", "price_group")

    op.create_unique_constraint(
        "uq_subscription_tier_period", "subscription_tier_period_pricing", ["tier", "period_months"]
    )
    op.create_foreign_key(
        "subscription_tier_period_pricing_tier_fkey",
        "subscription_tier_period_pricing",
        "subscription_tier_pricing",
        ["tier"],
        ["tier"],
        ondelete="CASCADE",
    )
    op.drop_column("subscription_tier_period_pricing", "price_group")

    op.drop_column("cities", "price_group")
    op.drop_column("cities", "country")
