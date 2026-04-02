"""Trainer primary arena; booking stores resolved arena for client-facing location.

Revision ID: 0076_trainer_primary_arena
Revises: 0075_trainer_photo_pending
"""

from alembic import op
import sqlalchemy as sa


revision = "0076_trainer_primary_arena"
down_revision = "0075_trainer_photo_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainers",
        sa.Column("primary_arena_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_trainers_primary_arena_id_arenas",
        "trainers",
        "arenas",
        ["primary_arena_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "bookings",
        sa.Column("arena_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bookings_arena_id_arenas",
        "bookings",
        "arenas",
        ["arena_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Backfill primary: smallest arena_id per trainer (stable default).
    op.execute(
        """
        UPDATE trainers t
        SET primary_arena_id = sub.min_aid
        FROM (
            SELECT trainer_id, MIN(arena_id) AS min_aid
            FROM trainer_arenas
            GROUP BY trainer_id
        ) sub
        WHERE t.id = sub.trainer_id
          AND t.primary_arena_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_bookings_arena_id_arenas", "bookings", type_="foreignkey")
    op.drop_column("bookings", "arena_id")
    op.drop_constraint("fk_trainers_primary_arena_id_arenas", "trainers", type_="foreignkey")
    op.drop_column("trainers", "primary_arena_id")
