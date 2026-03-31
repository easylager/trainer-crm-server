"""Subscription plans and trainer subscriptions (platform billing).

Revision ID: 0042_subscription
Revises: 0041_phone_normalized
"""
from alembic import op
import sqlalchemy as sa


revision = "0042_subscription"
down_revision = "0041_phone_normalized"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("period_days", sa.Integer(), nullable=False),
        sa.Column("is_trial", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "trainer_subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payment_external_id", sa.String(256), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trainer_subscriptions_trainer_id", "trainer_subscriptions", ["trainer_id"])
    op.create_index("ix_trainer_subscriptions_plan_id", "trainer_subscriptions", ["plan_id"])
    op.create_index("ix_trainer_subscriptions_expires_at", "trainer_subscriptions", ["expires_at"])

    op.create_table(
        "trainer_invoices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("subscription_plan_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_external_id", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["subscription_plan_id"], ["subscription_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trainer_invoices_trainer_id", "trainer_invoices", ["trainer_id"])
    op.create_index("ix_trainer_invoices_subscription_plan_id", "trainer_invoices", ["subscription_plan_id"])

    # Seed: Trial (0 BYN, 14 days), Month (29 BYN, 30 days)
    op.execute("""
        INSERT INTO subscription_plans (name, price_cents, period_days, is_trial, sort_order)
        VALUES
            ('Пробный период', 0, 14, true, 0),
            ('Месяц', 2900, 30, false, 1)
    """)


def downgrade() -> None:
    op.drop_table("trainer_invoices")
    op.drop_table("trainer_subscriptions")
    op.drop_table("subscription_plans")
