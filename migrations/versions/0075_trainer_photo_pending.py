"""Active trainers: photo_pending JSONB until moderation approves (catalog keeps old trainer_photos).

Revision ID: 0075_trainer_photo_pending
Revises: 0074_trainer_profile_pending
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0075_trainer_photo_pending"
down_revision = "0074_trainer_profile_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("photo_pending", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainers", "photo_pending")
