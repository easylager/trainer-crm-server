"""trainer_invoices: referral bonus days applied to subscription invoice (prorated amount)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0121_trainer_invoice_referral"
down_revision = "0120_referral_milestone_bonuses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_invoices",
        sa.Column("referral_bonus_days_applied", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "trainer_invoices",
        sa.Column("amount_cents_before_referral", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE trainer_invoices SET amount_cents_before_referral = amount_cents WHERE amount_cents_before_referral IS NULL")
    op.alter_column("trainer_invoices", "referral_bonus_days_applied", server_default=None)


def downgrade() -> None:
    op.drop_column("trainer_invoices", "amount_cents_before_referral")
    op.drop_column("trainer_invoices", "referral_bonus_days_applied")
