"""trainer_invoices: snapshot for tier/constructor checkout (ERIP / manual confirm).

Revision ID: 0108
Revises: 0107
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0108_trainer_invoice_catalog"
down_revision = "0107_trainer_services_client"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_invoices",
        sa.Column("checkout_modules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "trainer_invoices",
        sa.Column("checkout_billing_period_months", sa.Integer(), nullable=True),
    )
    op.add_column(
        "trainer_invoices",
        sa.Column("checkout_bundle_tier", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_invoices", "checkout_bundle_tier")
    op.drop_column("trainer_invoices", "checkout_billing_period_months")
    op.drop_column("trainer_invoices", "checkout_modules")
