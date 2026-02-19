"""Add education to profile and trainer_photos table (at least one photo required in app).

Revision ID: 0004_education_photos
Revises: 0003_profile_services
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_education_photos"
down_revision = "0003_profile_services"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("education", sa.Text(), nullable=True),
    )
    op.create_table(
        "trainer_photos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("file_key", sa.String(512), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trainer_photos_trainer_id"), "trainer_photos", ["trainer_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_trainer_photos_trainer_id"), table_name="trainer_photos")
    op.drop_table("trainer_photos")
    op.drop_column("trainer_profiles", "education")
