"""bookings.is_sandbox — marks onboarding demo bookings excluded from stats and milestones."""

from alembic import op

revision = "0128_booking_is_sandbox"
down_revision = "0127_trainer_group_classes_dflt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS is_sandbox BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP COLUMN IF EXISTS is_sandbox")
