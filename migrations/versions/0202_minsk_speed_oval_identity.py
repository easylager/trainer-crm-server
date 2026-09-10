"""Fix arena_id=115 when prod row is Moscow CSKA; Конькобежный стадион belongs in Minsk.

Revision ID: 0202_minsk_speed_oval_identity
Revises: 0201_merge_interest_share
"""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import op

revision = "0202_minsk_speed_oval_identity"
down_revision = "0201_merge_interest_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Must use Alembic's connection: env.py wraps the whole upgrade in one
    # transaction, so a second engine would not see uncommitted schema (CI fails
    # with UndefinedTableError: relation "cities" does not exist).
    #
    # Railway historically invoked the `alembic` console script without
    # PYTHONPATH; keep repo root importable even then.
    root = Path(__file__).resolve().parents[2]
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)

    from src.application.minsk_speed_oval_identity import repair_speed_oval_identity_sync

    repair_speed_oval_identity_sync(op.get_bind())


def downgrade() -> None:
    """Data repair — no downgrade."""
