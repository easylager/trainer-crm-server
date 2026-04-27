"""New trainer_profiles rows: group_classes_enabled defaults to true (first-time UX + trial)."""

from alembic import op

revision = "0127_trainer_group_classes_dflt"
down_revision = "0126_trial_roi_recap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled SET DEFAULT true"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE trainer_profiles ALTER COLUMN group_classes_enabled SET DEFAULT false"
    )
