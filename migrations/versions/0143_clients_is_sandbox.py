"""clients.is_sandbox — onboarding demo client, isolated from CRM scope, stats, rhythm hints.

Backfill: a client is considered sandbox if every booking row referencing them is sandbox
(a real CRM client never collapses to sandbox even if a sandbox booking touched them).

Revision ID: 0143_clients_is_sandbox
Revises: 0142_trainer_client_roster
"""

from __future__ import annotations

from alembic import op

revision = "0143_clients_is_sandbox"
down_revision = "0142_trainer_client_roster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_sandbox BOOLEAN NOT NULL DEFAULT false"
    )
    # Backfill: clients whose every booking is sandbox (and at least one exists) are demo identities.
    # Real clients with even a single non-sandbox booking stay non-sandbox — preserves CRM data.
    op.execute(
        """
        UPDATE clients c
        SET is_sandbox = true
        WHERE EXISTS (
            SELECT 1 FROM bookings b
            WHERE b.client_id = c.id
              AND b.is_sandbox = true
        )
        AND NOT EXISTS (
            SELECT 1 FROM bookings b
            WHERE b.client_id = c.id
              AND b.is_sandbox = false
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_clients_is_sandbox ON clients (is_sandbox) WHERE is_sandbox = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_clients_is_sandbox")
    op.execute("ALTER TABLE clients DROP COLUMN IF EXISTS is_sandbox")
