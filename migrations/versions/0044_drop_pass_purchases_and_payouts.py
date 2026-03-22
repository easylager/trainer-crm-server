"""Drop pass_redemptions, pass_instances, pass_purchases, trainer_payouts.

Abonements are only a price list (trainer_pass_products); no payment through platform.
Revision ID: 0044_drop_passes
Revises: 0043_payouts
"""
from alembic import op


revision = "0044_drop_passes"
down_revision = "0043_payouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("pass_redemptions")
    op.drop_table("pass_instances")
    op.drop_table("pass_purchases")
    op.drop_table("trainer_payouts")


def downgrade() -> None:
    raise NotImplementedError("Downgrade not implemented: tables were removed (pass_* , trainer_payouts)")
