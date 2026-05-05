"""trainer_services.ui_accent — optional preset border color for hub + schedule rows.

Revision ID: 0144_trainer_services_ui_accent
Revises: 0143_clients_is_sandbox
"""

from __future__ import annotations

from alembic import op

revision = "0144_trainer_services_ui_accent"
down_revision = "0143_clients_is_sandbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_services ADD COLUMN IF NOT EXISTS ui_accent VARCHAR(24)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trainer_services DROP COLUMN IF EXISTS ui_accent")
