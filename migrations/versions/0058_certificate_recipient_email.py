"""Add recipient_email to certificate_instances (for send link by email)."""

from alembic import op
import sqlalchemy as sa


revision = "0058_certificate_recipient_email"
down_revision = "0057_pass_redemptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificate_instances",
        sa.Column("recipient_email", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("certificate_instances", "recipient_email")
