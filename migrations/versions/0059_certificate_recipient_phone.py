"""Add recipient_phone to certificate_instances (for welcome-link onboarding)."""

from alembic import op
import sqlalchemy as sa


revision = "0059_certificate_recipient_phone"
down_revision = "0058_certificate_recipient_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificate_instances",
        sa.Column("recipient_phone", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("certificate_instances", "recipient_phone")
