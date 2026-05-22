"""Merge parallel heads: main chain (0155 audit) + invite-link backfill branch."""

from alembic import op

revision = "0156_merge_audit_backfill"
down_revision = ("0150_backfill_invite_copy_ts", "0155_audit_no_fk")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
