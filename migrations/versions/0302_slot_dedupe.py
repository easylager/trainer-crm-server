"""slots: drop free identical twins, forbid new ones (unique index on live slots).

Revision ID: 0302_slot_dedupe
Revises: 0301_game_views_refresh
Create Date: 2026-11-02

Hotfix numbering: a release batch branch already uses revisions up to 0301 — the coordinator
reconciles the id/down_revision when the two meet.

Two parallel POST /schedule/slots (double tap, network retry) used to insert every slot of the day
twice. The writers now take a per-trainer advisory lock; this index is the backstop.

Before creating the index the migration removes only the *free* twin of a duplicated slot:
status 'available', no bookings of any status. A slot with a booking is never touched. If two
twins both carry bookings the index is not created (logged) instead of failing the deploy —
those groups have to be resolved by hand (see scripts/dedupe_slots_dry_run.py).
"""
from alembic import op

revision = "0302_slot_dedupe"
down_revision = "0301_game_views_refresh"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_slots_live_identical"

# Same key as the index: one live (non-cancelled) slot per trainer / day / window / venue.
DEDUPE_SQL = """
WITH ranked AS (
    SELECT s.id,
           s.status,
           EXISTS (SELECT 1 FROM bookings b WHERE b.slot_id = s.id) AS has_booking,
           ROW_NUMBER() OVER (
               PARTITION BY s.trainer_id, s.slot_date, s.start_time, s.end_time, COALESCE(s.arena_id, 0)
               ORDER BY (EXISTS (SELECT 1 FROM bookings b WHERE b.slot_id = s.id)) DESC,
                        (s.status = 'booked') DESC,
                        s.id
           ) AS rn
    FROM slots s
    WHERE s.status <> 'cancelled'
)
DELETE FROM slots
WHERE id IN (
    SELECT id FROM ranked WHERE rn > 1 AND status = 'available' AND NOT has_booking
)
"""

REMAINING_SQL = """
SELECT COUNT(*) FROM (
    SELECT 1 FROM slots
    WHERE status <> 'cancelled'
    GROUP BY trainer_id, slot_date, start_time, end_time, COALESCE(arena_id, 0)
    HAVING COUNT(*) > 1
) d
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(DEDUPE_SQL)
    remaining = bind.exec_driver_sql(REMAINING_SQL).scalar()
    if remaining:
        print(f"[0285] {remaining} duplicate slot group(s) with bookings on several twins — unique index skipped")
        return
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
        ON slots (trainer_id, slot_date, start_time, end_time, COALESCE(arena_id, 0))
        WHERE status <> 'cancelled'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
