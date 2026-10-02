"""Rename venue_type 'ice' → 'arena' and drop choreo/pool.

The venue type set is being simplified to what trainers actually create:
arena (ice), gym, roller, outdoor, other. Choreo and pool are not
independent venue types — they are zones inside an arena or gym.

This migration:
1. Renames 'ice' → 'arena' in the arenas table
2. Updates the server_default
3. Removes any 'choreo' or 'pool' rows (there are none in production,
   but the migration is idempotent)

Revision ID: 0210_venue_type_ice_to_arena
Revises: 0209_collective_catalog_state
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0210_venue_type_ice_to_arena"
down_revision = "0209_collective_catalog_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old CHECK constraint
    op.execute("ALTER TABLE arenas DROP CONSTRAINT ck_arenas_venue_type")
    # Rename 'ice' → 'arena'
    op.execute("UPDATE arenas SET venue_type = 'arena' WHERE venue_type = 'ice'")
    # Remove choreo and pool (should be no-op in production)
    op.execute("DELETE FROM arenas WHERE venue_type IN ('choreo', 'pool')")
    # Add new CHECK constraint
    op.execute(
        "ALTER TABLE arenas ADD CONSTRAINT ck_arenas_venue_type "
        "CHECK (venue_type = ANY (ARRAY['arena', 'gym', 'roller', 'outdoor', 'other']))"
    )
    # Update server_default
    op.alter_column(
        "arenas",
        "venue_type",
        server_default="arena",
    )


def downgrade() -> None:
    # Drop new CHECK constraint
    op.execute("ALTER TABLE arenas DROP CONSTRAINT ck_arenas_venue_type")
    # Revert 'arena' → 'ice'
    op.execute("UPDATE arenas SET venue_type = 'ice' WHERE venue_type = 'arena'")
    # Restore old CHECK constraint
    op.execute(
        "ALTER TABLE arenas ADD CONSTRAINT ck_arenas_venue_type "
        "CHECK (venue_type = ANY (ARRAY['ice', 'gym', 'choreo', 'pool', 'outdoor', 'other']))"
    )
    # Restore server_default
    op.alter_column(
        "arenas",
        "venue_type",
        server_default="ice",
    )
