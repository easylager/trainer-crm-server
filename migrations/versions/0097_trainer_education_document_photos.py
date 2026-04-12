"""Add uploaded diploma/certificate photos to trainer_education.

Revision ID: 0097_trainer_edu_doc_photos
Revises: 0096_arena_schedule_preset_slot
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0097_trainer_edu_doc_photos"
down_revision = "0096_arena_schedule_preset_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_education",
        sa.Column("document_photos", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_education", "document_photos")
