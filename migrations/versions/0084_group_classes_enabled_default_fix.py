"""Restore DEFAULT on group_classes_enabled if 0083 dropped it (INSERTs omitting column need false)."""

from alembic import op


revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled SET DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled DROP DEFAULT"
    )
