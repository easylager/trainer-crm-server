"""Trainer pass products: optional tier_kind restrictions via junction table (empty = all tiers).

Revision ID: 0161_pass_product_tiers
Revises: 0160_trainer_birth_date
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0161_pass_product_tiers"
down_revision = "0160_trainer_birth_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_pass_product_tiers",
        sa.Column("pass_product_id", sa.Integer(), nullable=False),
        sa.Column("tier_kind", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["pass_product_id"],
            ["trainer_pass_products.id"],
            name="fk_tpp_tiers_pass_product",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pass_product_id", "tier_kind"),
    )
    op.create_index(
        "ix_tpp_tiers_pass_product_id",
        "trainer_pass_product_tiers",
        ["pass_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tpp_tiers_pass_product_id", table_name="trainer_pass_product_tiers")
    op.drop_table("trainer_pass_product_tiers")
