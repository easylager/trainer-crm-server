"""Arena preset: ТЦ «Тринити» — старты каждый час в :00, 11:00–22:00, 45 мин.

Revision ID: 0123_trinity_arena_preset
Revises: 0122_zamok_arena_hourly_10
Create Date: 2026-04-26

Arena row must exist with name exactly: ТЦ "Тринити" (ASCII quotes as in CRM).
"""

from alembic import op

revision = "0123_trinity_arena_preset"
down_revision = "0122_zamok_arena_hourly_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO arena_schedule_presets (
            arena_id, grid_kind, minute_offset, hour_start, hour_end, slot_duration_minutes
        )
        SELECT id, 'hourly_minute', 0, 11, 22, 45
        FROM arenas
        WHERE name = 'ТЦ "Тринити"'
        LIMIT 1
        ON CONFLICT (arena_id) DO UPDATE SET
            grid_kind = EXCLUDED.grid_kind,
            minute_offset = EXCLUDED.minute_offset,
            hour_start = EXCLUDED.hour_start,
            hour_end = EXCLUDED.hour_end,
            slot_duration_minutes = EXCLUDED.slot_duration_minutes
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM arena_schedule_presets
        WHERE arena_id IN (
            SELECT id FROM arenas WHERE name = 'ТЦ "Тринити"' LIMIT 1
        )
        """
    )
