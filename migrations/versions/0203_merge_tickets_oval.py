"""Merge 0202_arena_tickets_url and 0202_minsk_speed_oval_identity.

Both branched from 0201_merge_interest_share (tickets CTA vs Minsk oval identity).
Empty upgrade — schema/data already applied on either head.

Revision ID: 0203_merge_tickets_oval
Revises: 0202_arena_tickets_url, 0202_minsk_speed_oval_identity
"""
from __future__ import annotations


revision = "0203_merge_tickets_oval"
down_revision = ("0202_arena_tickets_url", "0202_minsk_speed_oval_identity")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
