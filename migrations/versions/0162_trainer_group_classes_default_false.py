"""New trainer_profiles rows: group_classes_enabled defaults to false (individual slots only)."""

from alembic import op

revision = "0162_group_classes_dflt_false"
down_revision = "0161_pass_product_tiers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled SET DEFAULT false"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled SET DEFAULT true"
    )
