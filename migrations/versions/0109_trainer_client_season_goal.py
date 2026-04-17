"""trainer_client_notes: season_goal for trainer client dossier."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0109_trainer_client_season_goal"
down_revision = "0108_trainer_invoice_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_client_notes",
        sa.Column("season_goal", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_client_notes", "season_goal")
