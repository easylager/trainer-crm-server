"""Per-client self-booking time window (morning / afternoon / evening) for a trainer."""

from alembic import op
import sqlalchemy as sa

revision = "0153_client_booking_daypart"
down_revision = "0152_cert_product_description"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_client_notes",
        sa.Column("preferred_booking_daypart", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_client_notes", "preferred_booking_daypart")
