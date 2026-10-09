"""trainer_services.is_online — online vs venue XOR per trainer offering.

Revision ID: 0225_trainer_services_is_online
Revises: 0224_hockey_practice_kind
"""

from __future__ import annotations

from alembic import op

revision = "0225_trainer_services_is_online"
down_revision = "0224_hockey_practice_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_services "
        "ADD COLUMN IF NOT EXISTS is_online BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trainer_services DROP COLUMN IF EXISTS is_online")
