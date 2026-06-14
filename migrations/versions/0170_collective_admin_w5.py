"""Collective admin role + trainer studio_access_mode (ADR-003 W5)."""

from alembic import op
import sqlalchemy as sa

revision = "0170_collective_admin_w5"
down_revision = "0169_collective_multi_w4"
branch_labels = None
depends_on = None

MEMBER_ROLES = ("owner", "admin", "member")
STUDIO_ACCESS_MODES = ("full_trainer", "studio_admin_only")


def upgrade() -> None:
    op.execute("ALTER TABLE collective_members DROP CONSTRAINT IF EXISTS ck_collective_members_role")
    op.execute(
        "ALTER TABLE collective_members ADD CONSTRAINT ck_collective_members_role "
        "CHECK (role IN ('owner', 'admin', 'member'))"
    )
    op.add_column(
        "trainers",
        sa.Column(
            "studio_access_mode",
            sa.String(32),
            nullable=False,
            server_default="full_trainer",
        ),
    )
    op.execute(
        "ALTER TABLE trainers ADD CONSTRAINT ck_trainers_studio_access_mode "
        "CHECK (studio_access_mode IN ('full_trainer', 'studio_admin_only'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trainers DROP CONSTRAINT IF EXISTS ck_trainers_studio_access_mode")
    op.drop_column("trainers", "studio_access_mode")
    op.execute("ALTER TABLE collective_members DROP CONSTRAINT IF EXISTS ck_collective_members_role")
    op.execute(
        "UPDATE collective_members SET role = 'member' WHERE role = 'admin'"
    )
    op.execute(
        "ALTER TABLE collective_members ADD CONSTRAINT ck_collective_members_role "
        "CHECK (role IN ('owner', 'member'))"
    )
