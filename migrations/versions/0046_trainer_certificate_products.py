"""Add trainer_certificate_products: certificate amounts (fixed or any amount).

Revision ID: 0046_certificate_products
Revises: 0045_plans_3m_1y
"""
from alembic import op
import sqlalchemy as sa


revision = "0046_certificate_products"
down_revision = "0045_plans_3m_1y"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_certificate_products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),  # NULL = "любая сумма"
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trainer_certificate_products_trainer_id",
        "trainer_certificate_products",
        ["trainer_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trainer_certificate_products_trainer_id",
        table_name="trainer_certificate_products",
    )
    op.drop_table("trainer_certificate_products")
