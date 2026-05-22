"""Audit log: drop FK constraints so events always append (ids are denormalized)."""

from alembic import op

revision = "0155_audit_no_fk"
down_revision = "0154_platform_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("platform_audit_events_trainer_id_fkey", "platform_audit_events", type_="foreignkey")
    op.drop_constraint("platform_audit_events_client_id_fkey", "platform_audit_events", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key(
        "platform_audit_events_client_id_fkey",
        "platform_audit_events",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "platform_audit_events_trainer_id_fkey",
        "platform_audit_events",
        "trainers",
        ["trainer_id"],
        ["id"],
        ondelete="SET NULL",
    )
