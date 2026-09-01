"""Catalog listing becomes an opt-in: new trainers are not published by default.

Before this, ``is_catalog_visible`` defaulted to TRUE and the Mini App only exposed the
toggle once ``status = 'active'``. Combined with the profile screen auto-submitting to
moderation on every save, a trainer who merely filled in their card was published to the
public catalog without ever being asked — and could only opt out after the fact.

Backfill is deliberately narrow: trainers who already queued for moderation
(``moderation_submitted_at IS NOT NULL``) or are already ``active`` clearly asked to be
listed, and keep their current value. Only never-submitted onboarding rows — who were
never asked — are reset to FALSE. They are not in the catalog today either way
(listings require ``status = 'active'``), so nobody loses visibility.

Revision ID: 0182_catalog_opt_in
Revises: 0181_profile_nudges
Create Date: 2026-09-01
"""
from alembic import op


revision = "0182_catalog_opt_in"
down_revision = "0181_profile_nudges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE trainers ALTER COLUMN is_catalog_visible SET DEFAULT false")
    op.execute(
        """
        UPDATE trainers
        SET is_catalog_visible = false
        WHERE is_catalog_visible = true
          AND status <> 'active'
          AND moderation_submitted_at IS NULL
        """
    )


def downgrade() -> None:
    # Intent cannot be recovered per-row; restore the old default only.
    op.execute("ALTER TABLE trainers ALTER COLUMN is_catalog_visible SET DEFAULT true")
