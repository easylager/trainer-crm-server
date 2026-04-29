"""ТЦ Замок: сетка стартов :15 каждого часа, последнее начало — 22:15 (была :10, до 21:10)."""

from __future__ import annotations

from alembic import op

revision = "0136_zamok_arena_hourly_15"
down_revision = "0135_edge_booking_saved_service"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE arena_schedule_presets AS p
        SET minute_offset = 15,
            hour_start = 10,
            hour_end = 22
        FROM arenas AS a
        WHERE p.arena_id = a.id
          AND a.name = 'ТЦ Замок'
          AND p.grid_kind = 'hourly_minute'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE arena_schedule_presets AS p
        SET minute_offset = 10,
            hour_start = 10,
            hour_end = 21
        FROM arenas AS a
        WHERE p.arena_id = a.id
          AND a.name = 'ТЦ Замок'
          AND p.grid_kind = 'hourly_minute'
        """
    )
