"""Add platform_fee_cents, trainer_amount_cents to pass_purchases; create trainer_payouts.

Revision ID: 0043_payouts
Revises: 0042_subscription
"""
from alembic import op
import sqlalchemy as sa


revision = "0043_payouts"
down_revision = "0042_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pass_purchases",
        sa.Column("platform_fee_cents", sa.Integer(), nullable=True),
    )
    op.add_column(
        "pass_purchases",
        sa.Column("trainer_amount_cents", sa.Integer(), nullable=True),
    )

    op.create_table(
        "trainer_payouts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_earned_cents", sa.Integer(), nullable=False),
        sa.Column("platform_fee_total_cents", sa.Integer(), nullable=False),
        sa.Column("amount_payable_cents", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_details", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trainer_payouts_trainer_id", "trainer_payouts", ["trainer_id"])
    op.create_index("ix_trainer_payouts_period_end", "trainer_payouts", ["period_end"])


def downgrade() -> None:
    op.drop_table("trainer_payouts")
    op.drop_column("pass_purchases", "trainer_amount_cents")
    op.drop_column("pass_purchases", "platform_fee_cents")
