"""Legacy revision placeholder (was removed from repo).

Deployed databases may still list ``0139_trainers_grid_step_5`` in ``alembic_version``.
This empty migration restores a loadable graph; ``0140_schedule_grid_remove_five_minute_step``
applies the real schema revert (no 5-minute grid step).
"""

from __future__ import annotations

from alembic import op

revision = "0139_trainers_grid_step_5"
down_revision = "0138_clients_middle_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
