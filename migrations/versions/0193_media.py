"""Media table for owner-typed catalog images (TASK-049).

Arena hero/gallery rows live here. Trainer catalog photos stay in trainer_photos
(no data migration). License is required; non-own needs source_url or attribution.

Revision ID: 0193_media
Revises: 0192_arena_profiles
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0193_media"
down_revision = "0192_arena_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_type", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("variants", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("blurhash", sa.String(length=64), nullable=True),
        sa.Column("license", sa.String(length=20), nullable=False),
        sa.Column("attribution", sa.String(length=256), nullable=True),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.CheckConstraint(
            "owner_type IN ('arena', 'coach', 'collective')",
            name="ck_media_owner_type",
        ),
        sa.CheckConstraint(
            "license IN ('own', 'operator', 'user', 'permitted')",
            name="ck_media_license",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'published', 'rejected')",
            name="ck_media_status",
        ),
        sa.CheckConstraint(
            "license = 'own' OR COALESCE(btrim(source_url), '') <> '' "
            "OR COALESCE(btrim(attribution), '') <> ''",
            name="ck_media_license_source",
        ),
    )
    op.create_index("ix_media_owner", "media", ["owner_type", "owner_id"])


def downgrade() -> None:
    op.drop_index("ix_media_owner", table_name="media")
    op.drop_table("media")
