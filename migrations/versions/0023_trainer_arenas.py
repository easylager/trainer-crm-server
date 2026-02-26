"""Trainer–Arena many-to-many: trainers can work at multiple arenas.

Revision ID: 0023_trainer_arenas
Revises: 0022_arena_address_coords
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_trainer_arenas"
down_revision = "0022_arena_address_coords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_arenas",
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("trainer_id", "arena_id", name="uq_trainer_arenas_trainer_arena"),
    )
    op.create_index("ix_trainer_arenas_arena_id", "trainer_arenas", ["arena_id"], unique=False)
    op.create_index("ix_trainer_arenas_trainer_id", "trainer_arenas", ["trainer_id"], unique=False)

    # Backfill from existing slots: trainers that have slots in an arena are linked to that arena
    op.execute("""
        INSERT INTO trainer_arenas (trainer_id, arena_id)
        SELECT DISTINCT trainer_id, arena_id FROM slots WHERE arena_id IS NOT NULL
        ON CONFLICT (trainer_id, arena_id) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_index("ix_trainer_arenas_trainer_id", table_name="trainer_arenas")
    op.drop_index("ix_trainer_arenas_arena_id", table_name="trainer_arenas")
    op.drop_table("trainer_arenas")
