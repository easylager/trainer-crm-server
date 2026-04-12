"""Optional fixed slot duration per arena preset (e.g. 45 min for ТЦ Замок).

Revision ID: 0096_arena_schedule_preset_slot
Revises: 0095_arena_schedule_presets
"""
from alembic import op
import sqlalchemy as sa


revision = "0096_arena_schedule_preset_slot"
down_revision = "0095_arena_schedule_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "arena_schedule_presets",
        sa.Column("slot_duration_minutes", sa.SmallInteger(), nullable=True),
    )
    # ТЦ Замок: фиксированные 45 мин на слот (сетка стартов :10 — в 0095)
    op.execute(
        """
        UPDATE arena_schedule_presets
        SET slot_duration_minutes = 45
        WHERE arena_id IN (SELECT id FROM arenas WHERE name = 'ТЦ Замок')
        """
    )


def downgrade() -> None:
    op.drop_column("arena_schedule_presets", "slot_duration_minutes")
