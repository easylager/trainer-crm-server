"""Fix arena_id=115 when prod row is Moscow CSKA; Конькобежный стадион belongs in Minsk.

Revision ID: 0202_minsk_speed_oval_identity
Revises: 0201_merge_interest_share
"""
from __future__ import annotations

from alembic import op

revision = "0202_minsk_speed_oval_identity"
down_revision = "0201_merge_interest_share"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Must use Alembic's connection: env.py wraps the whole upgrade in one
    # transaction, so a second engine would not see uncommitted schema (CI fails
    # with UndefinedTableError: relation "cities" does not exist).
    from src.application.minsk_speed_oval_identity import repair_speed_oval_identity_sync

    repair_speed_oval_identity_sync(op.get_bind())


def downgrade() -> None:
    """Data repair — no downgrade."""
