"""Optional per-seat group slot price on trainer_services (fallback: anchor price_cents).

Revision ID: 0098_ts_group_price_cents
Revises: 0097_trainer_edu_doc_photos
"""

from alembic import op
import sqlalchemy as sa


revision = "0098_ts_group_price_cents"
down_revision = "0097_trainer_edu_doc_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_services",
        sa.Column("group_price_cents", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_services", "group_price_cents")
