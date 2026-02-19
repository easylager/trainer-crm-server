"""Add first_name, last_name, age (required), experience (optional) to trainer_profiles.

Revision ID: 0005_profile_name_age
Revises: 0004_education_photos
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_profile_name_age"
down_revision = "0004_education_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trainer_profiles", sa.Column("first_name", sa.String(64), nullable=True))
    op.add_column("trainer_profiles", sa.Column("last_name", sa.String(64), nullable=True))
    op.add_column("trainer_profiles", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("trainer_profiles", sa.Column("experience_years", sa.Integer(), nullable=True))
    # Backfill not required; then alter to NOT NULL if we want (after backfill)
    # For now leave nullable so existing rows don't break; app can enforce required on create/update


def downgrade() -> None:
    op.drop_column("trainer_profiles", "experience_years")
    op.drop_column("trainer_profiles", "age")
    op.drop_column("trainer_profiles", "last_name")
    op.drop_column("trainer_profiles", "first_name")
