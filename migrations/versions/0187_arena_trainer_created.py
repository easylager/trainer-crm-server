"""Arena trainer-created moderation fields.

Lets a trainer create a real arena row directly from the profile screen (TASK-046)
instead of only filing a text support request. New trainer-created arenas start
``is_confirmed=false`` — visible to trainers of the same city immediately, hidden
from the public client catalog (``GET /api/public/arenas``) until an admin confirms.
Existing/admin-seeded arenas backfill to ``is_confirmed=true`` so today's catalog
behavior is unchanged until a trainer actually creates a new one.

Revision ID: 0187_arena_trainer_created
Revises: 0186_client_profile_links
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0187_arena_trainer_created"
down_revision = "0186_client_profile_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arenas",
        sa.Column("created_by_trainer_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "arenas",
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "arenas",
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "arenas",
        sa.Column("confirmed_by_admin_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_arenas_created_by_trainer",
        "arenas",
        "trainers",
        ["created_by_trainer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_arenas_created_by_trainer", "arenas", ["created_by_trainer_id"])


def downgrade() -> None:
    op.drop_index("ix_arenas_created_by_trainer", table_name="arenas")
    op.drop_constraint("fk_arenas_created_by_trainer", "arenas", type_="foreignkey")
    op.drop_column("arenas", "confirmed_by_admin_id")
    op.drop_column("arenas", "confirmed_at")
    op.drop_column("arenas", "is_confirmed")
    op.drop_column("arenas", "created_by_trainer_id")
