"""Vitebsk ice palace buy link — 24afisha event page.

The place-page «Купить билет» reads arena_profiles.tickets_url.
Sessions come from the 24afisha schedule parser; this only fills the
arena-level link when it is still empty.

Revision ID: 0254_vitebsk_tickets_url
Revises: 0253_slots_is_online
"""

from __future__ import annotations

from alembic import op

revision = "0254_vitebsk_tickets_url"
down_revision = "0253_slots_is_online"
branch_labels = None
depends_on = None

_URL = "https://24afisha.by/ru/vitebsk/event/massovoe-katanie-v-vitebskom-dvortse-sporta"
_ARENA_ID = 29


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE arena_profiles
        SET tickets_url = '{_URL}'
        WHERE arena_id = {_ARENA_ID}
          AND (tickets_url IS NULL OR btrim(tickets_url) = '')
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        UPDATE arena_profiles
        SET tickets_url = NULL
        WHERE arena_id = {_ARENA_ID}
          AND tickets_url = '{_URL}'
        """
    )
