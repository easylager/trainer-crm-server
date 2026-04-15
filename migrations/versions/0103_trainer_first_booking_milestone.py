"""Trainer profile: first booking milestone + share-catalog tip timestamps."""

from alembic import op
import sqlalchemy as sa


revision = "0103_trainer_first_booking"
down_revision = "0102_booking_client_no_show"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("first_booking_milestone_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "trainer_profiles",
        sa.Column("share_catalog_tip_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "share_catalog_tip_sent_at")
    op.drop_column("trainer_profiles", "first_booking_milestone_at")
