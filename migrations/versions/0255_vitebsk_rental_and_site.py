"""Vitebsk ice palace: skate rental prices, club site, ticket page.

Place page reads rental rows from opening_hours and the two links from
arena_profiles. Session prices stay the ticket price; rental is two sizes,
so it does not go into the single price_rental_minor column.

Revision ID: 0255_vitebsk_rental_and_site
Revises: 0254_vitebsk_tickets_url
"""

from __future__ import annotations

from alembic import op

revision = "0255_vitebsk_rental_and_site"
down_revision = "0254_vitebsk_tickets_url"
branch_labels = None
depends_on = None

_SITE = "https://hc-vitebsk.by/"
_TICKETS = "https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta"
_OLD_SITE = "https://vitebsk.hockey.by/clubs/arena/massovoe-katanie/"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE arena_profiles
        SET website_url = '{_SITE}',
            tickets_url = '{_TICKETS}',
            opening_hours = COALESCE(opening_hours, '{{}}'::jsonb) || jsonb_build_object(
                'rental_title', 'Прокат коньков',
                'rental_note', 'Выдача коньков открывается за 1 час до начала сеанса.',
                'rental_catalog', jsonb_build_array(
                    jsonb_build_object('label', 'до 34 размера', 'price', '5,00 BYN'),
                    jsonb_build_object('label', 'от 35 размера', 'price', '10,00 BYN')
                )
            ),
            amenities = COALESCE(amenities, '{{}}'::jsonb) || '{{"skate_rental": true}}'::jsonb
        WHERE arena_id = 29
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE arena_profiles
        SET website_url = CASE
                WHEN website_url = '{_SITE}' THEN '{_OLD_SITE}'
                ELSE website_url
            END,
            opening_hours = opening_hours
                - 'rental_title' - 'rental_note' - 'rental_catalog',
            amenities = amenities - 'skate_rental'
        WHERE arena_id = 29
        """
    )
