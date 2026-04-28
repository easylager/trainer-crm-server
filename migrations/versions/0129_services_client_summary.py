"""Service catalog: optional client-facing summary for mini-app «what is this service» modal."""

import sqlalchemy as sha
from alembic import op

revision = "0129_services_client_summary"
down_revision = "0128_booking_is_sandbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "services",
        sha.Column("client_summary", sha.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("services", "client_summary")
