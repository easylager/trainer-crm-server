"""Backfill client_invite_link_first_copied_at from clients-in-bot and real bookings."""

from __future__ import annotations

from alembic import op

revision = "0150_backfill_invite_copy_ts"
down_revision = "0149_reminder_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE trainers t
        SET client_invite_link_first_copied_at = sub.ts
        FROM (
            SELECT
                t2.id AS trainer_id,
                COALESCE(
                    (
                        SELECT MIN(c.created_at)
                        FROM trainer_client_roster r
                        JOIN clients c ON c.id = r.client_id
                        WHERE r.trainer_id = t2.id
                          AND c.telegram_id IS NOT NULL
                          AND COALESCE(c.is_sandbox, false) = false
                    ),
                    (
                        SELECT MIN(b.created_at)
                        FROM bookings b
                        WHERE b.trainer_id = t2.id
                          AND COALESCE(b.is_sandbox, false) = false
                          AND b.status NOT IN ('cancelled', 'declined', 'trainer_removed')
                    )
                ) AS ts
            FROM trainers t2
            WHERE t2.client_invite_link_first_copied_at IS NULL
        ) sub
        WHERE t.id = sub.trainer_id
          AND sub.ts IS NOT NULL
        """
    )


def downgrade() -> None:
    pass
