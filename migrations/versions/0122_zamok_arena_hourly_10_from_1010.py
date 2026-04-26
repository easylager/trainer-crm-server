"""Restore ТЦ Замок hourly grid to :10 (10:10–21:10).

Revision ID: 0122_zamok_arena_hourly_10
Revises: 0121_trainer_invoice_referral
Create Date: 2026-04-24

Reverts 0112_zamok_arena_hourly_15_from_1015 (minute_offset 15 → 10).
"""

from alembic import op

revision = "0122_zamok_arena_hourly_10"
down_revision = "0121_trainer_invoice_referral"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE arena_schedule_presets p
        SET minute_offset = 10,
            hour_start = 10,
            hour_end = 21
        FROM arenas a
        WHERE p.arena_id = a.id
          AND a.name = 'ТЦ Замок'
          AND p.grid_kind = 'hourly_minute'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE arena_schedule_presets p
        SET minute_offset = 15,
            hour_start = 10,
            hour_end = 21
        FROM arenas a
        WHERE p.arena_id = a.id
          AND a.name = 'ТЦ Замок'
          AND p.grid_kind = 'hourly_minute'
        """
    )
