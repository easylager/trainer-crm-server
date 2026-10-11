"""Keep the FK Minsk rental caveat on the roller track only.

The mini-app used to print that sentence under every rental price list,
including Minikatok. The sentence now lives in opening_hours.rental_note.
"""

from __future__ import annotations

from alembic import op

revision = "0231_rental_section_copy"
down_revision = "0230_trainer_pass_validity_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles
        SET opening_hours = opening_hours
          || '{"rental_note": "Ориентиры проката ФК «Минск» — на кассе могут отличаться."}'::jsonb
        WHERE arena_id = 12
          AND opening_hours IS NOT NULL
          AND NOT (opening_hours ? 'rental_note')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles
        SET opening_hours = opening_hours - 'rental_note'
        WHERE arena_id = 12
          AND opening_hours->>'rental_note'
            = 'Ориентиры проката ФК «Минск» — на кассе могут отличаться.'
        """
    )
