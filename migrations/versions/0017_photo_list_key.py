"""Add list thumbnail key to trainer_photos for faster catalog loading.

Revision ID: 0017_photo_list_key
Revises: 0016_trainer_ratings
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_photo_list_key"
down_revision = "0016_trainer_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_photos",
        sa.Column("file_key_list", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_photos", "file_key_list")
