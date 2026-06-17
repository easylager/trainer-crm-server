"""Collective draft org profile: intended owner studio_access_mode at claim."""

from alembic import op
import sqlalchemy as sa

revision = "0171_collective_draft_profile"
down_revision = "0170_collective_admin_w5"
branch_labels = None
depends_on = None

STUDIO_ACCESS_MODES = ("full_trainer", "studio_admin_only")


def upgrade() -> None:
    op.add_column(
        "collectives",
        sa.Column(
            "owner_studio_access_mode",
            sa.String(32),
            nullable=False,
            server_default="full_trainer",
        ),
    )
    op.execute(
        "ALTER TABLE collectives ADD CONSTRAINT ck_collectives_owner_studio_access_mode "
        "CHECK (owner_studio_access_mode IN ('full_trainer', 'studio_admin_only'))"
    )
    op.add_column(
        "collectives",
        sa.Column(
            "organization_format",
            sa.String(32),
            nullable=False,
            server_default="ice",
        ),
    )


def downgrade() -> None:
    op.drop_column("collectives", "organization_format")
    op.execute(
        "ALTER TABLE collectives DROP CONSTRAINT IF EXISTS ck_collectives_owner_studio_access_mode"
    )
    op.drop_column("collectives", "owner_studio_access_mode")
