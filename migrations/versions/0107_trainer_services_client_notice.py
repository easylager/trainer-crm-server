"""Optional per-trainer-per-service notice: what is not included in price (skates, arena ticket, etc.)."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0107_trainer_services_client"
down_revision = "0106_welcome_link_client_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_services",
        sa.Column("client_notice", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_services", "client_notice")
