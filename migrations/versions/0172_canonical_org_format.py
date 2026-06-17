"""Normalize collective organization_format to studio | center | center_hybrid."""

from alembic import op

revision = "0172_canonical_org_format"
down_revision = "0171_collective_draft_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE collectives
        SET organization_format = 'studio'
        WHERE organization_format IN ('ice', 'coworking')
        """
    )
    op.execute(
        """
        UPDATE collectives
        SET organization_format = 'center'
        WHERE organization_format = 'manager'
        """
    )
    op.execute(
        """
        UPDATE collectives
        SET organization_format = 'center_hybrid'
        WHERE organization_format = 'center'
          AND owner_studio_access_mode = 'full_trainer'
        """
    )
    op.execute(
        """
        UPDATE collectives
        SET organization_format = 'center'
        WHERE organization_format = 'center'
          AND owner_studio_access_mode = 'studio_admin_only'
        """
    )
    op.alter_column("collectives", "organization_format", server_default="studio")


def downgrade() -> None:
    op.alter_column("collectives", "organization_format", server_default="ice")
