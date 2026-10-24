"""Gomel ice palace: show the skate rental price instead of «цена в кассе».

The weekly news post prints «Прокат коньков: 5 рублей»; the session rows already
carry it, but the place page services block had no row and fell back to the
generic «цена в кассе» line.

Revision ID: 0261_gomel_rental_price
Revises: 0260_single_trainer_plan
"""

from __future__ import annotations

from alembic import op

revision = "0261_gomel_rental_price"
down_revision = "0260_single_trainer_plan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles
        SET opening_hours = COALESCE(opening_hours, '{}'::jsonb) || jsonb_build_object(
            'rental_catalog', jsonb_build_array(
                jsonb_build_object('label', 'Прокат коньков', 'price', '5 BYN')
            )
        )
        WHERE arena_id = 33
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles
        SET opening_hours = opening_hours - 'rental_catalog'
        WHERE arena_id = 33
        """
    )
