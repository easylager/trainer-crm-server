"""Merge 0199 ice_city_interest and 0200 client_share_events.

The two trains branched from 0198: regional parsers added city-interest, client-premium
added share events. Empty upgrade — both tables already exist after either head.

Revision id kept under 32 chars (alembic_version.version_num).

Revision ID: 0201_merge_interest_share
Revises: 0199_ice_city_interest, 0200_client_share_events
"""
from __future__ import annotations


revision = "0201_merge_interest_share"
down_revision = ("0199_ice_city_interest", "0200_client_share_events")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
