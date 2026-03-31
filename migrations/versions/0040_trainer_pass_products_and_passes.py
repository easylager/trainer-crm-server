"""Add trainer pass products, purchases, pass instances and redemptions.

Revision ID: 0040_pass_products
Revises: 0039_client_cancel_comment
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0040_pass_products"
down_revision = "0039_client_cancel_comment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_pass_products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trainer_pass_products_trainer_id", "trainer_pass_products", ["trainer_id"])
    op.create_index("ix_trainer_pass_products_service_id", "trainer_pass_products", ["service_id"])

    op.create_table(
        "pass_purchases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("payment_external_id", sa.String(256), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["trainer_pass_products.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pass_purchases_client_id", "pass_purchases", ["client_id"])
    op.create_index("ix_pass_purchases_trainer_id", "pass_purchases", ["trainer_id"])
    op.create_index("ix_pass_purchases_product_id", "pass_purchases", ["product_id"])

    op.create_table(
        "pass_instances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purchase_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("sessions_total", sa.Integer(), nullable=False),
        sa.Column("sessions_left", sa.Integer(), nullable=False),
        sa.Column("product_snapshot", JSONB(), nullable=True),
        sa.Column("redemption_token", sa.String(64), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["purchase_id"], ["pass_purchases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("redemption_token", name="uq_pass_instances_redemption_token"),
    )
    op.create_index("ix_pass_instances_redemption_token", "pass_instances", ["redemption_token"])
    op.create_index("ix_pass_instances_client_id", "pass_instances", ["client_id"])
    op.create_index("ix_pass_instances_trainer_id", "pass_instances", ["trainer_id"])
    op.create_index("ix_pass_instances_purchase_id", "pass_instances", ["purchase_id"])

    op.create_table(
        "pass_redemptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pass_instance_id", sa.Integer(), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["pass_instance_id"], ["pass_instances.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pass_redemptions_pass_instance_id", "pass_redemptions", ["pass_instance_id"])
    op.create_index("ix_pass_redemptions_trainer_id", "pass_redemptions", ["trainer_id"])
    op.create_index("ix_pass_redemptions_booking_id", "pass_redemptions", ["booking_id"])


def downgrade() -> None:
    op.drop_table("pass_redemptions")
    op.drop_table("pass_instances")
    op.drop_table("pass_purchases")
    op.drop_table("trainer_pass_products")
