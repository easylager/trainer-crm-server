"""Arena schedule grid presets (e.g. hourly :10 for ТЦ Замок). Trainer inherits grid from primary arena.

Revision ID: 0095_arena_schedule_presets
Revises: 0094_subscription_default_prices
"""
from alembic import op
import sqlalchemy as sa


revision = "0095_arena_schedule_presets"
down_revision = "0094_subscription_default_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "arena_schedule_presets",
        sa.Column("arena_id", sa.Integer(), sa.ForeignKey("arenas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "grid_kind",
            sa.String(length=32),
            nullable=False,
            server_default="quarter_15",
        ),
        sa.Column("minute_offset", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("hour_start", sa.SmallInteger(), nullable=False, server_default="8"),
        sa.Column("hour_end", sa.SmallInteger(), nullable=False, server_default="21"),
    )
    op.create_index("ix_arena_schedule_presets_grid_kind", "arena_schedule_presets", ["grid_kind"])
    # ТЦ Замок: слоты на :10 каждого часа в рабочем окне (как у котокафе)
    op.execute(
        """
        INSERT INTO arena_schedule_presets (arena_id, grid_kind, minute_offset, hour_start, hour_end)
        SELECT id, 'hourly_minute', 10, 8, 21
        FROM arenas
        WHERE name = 'ТЦ Замок'
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_arena_schedule_presets_grid_kind", table_name="arena_schedule_presets")
    op.drop_table("arena_schedule_presets")
