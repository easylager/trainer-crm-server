"""Convert trainer status column to PostgreSQL ENUM.

Revision ID: 0007_trainer_status_enum
Revises: 0006_trainer_status
"""
from alembic import op


revision = "0007_trainer_status_enum"
down_revision = "0006_trainer_status"
branch_labels = None
depends_on = None

ENUM_NAME = "trainer_status_enum"
ENUM_VALUES = (
    "pending_profile",
    "pending_contract",
    "pending_payment",
    "active",
    "deactivated",
)


def upgrade() -> None:
    op.execute(
        f"CREATE TYPE {ENUM_NAME} AS ENUM ({', '.join(repr(v) for v in ENUM_VALUES)})"
    )
    op.execute("ALTER TABLE trainers ALTER COLUMN status DROP DEFAULT")
    op.execute(
        f"ALTER TABLE trainers ALTER COLUMN status TYPE {ENUM_NAME} "
        f"USING status::text::{ENUM_NAME}"
    )
    op.execute(f"ALTER TABLE trainers ALTER COLUMN status SET DEFAULT 'pending_profile'::{ENUM_NAME}")


def downgrade() -> None:
    op.execute("ALTER TABLE trainers ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE trainers ALTER COLUMN status TYPE VARCHAR(32) USING status::text")
    op.execute("ALTER TABLE trainers ALTER COLUMN status SET DEFAULT 'pending_profile'")
    op.execute(f"DROP TYPE {ENUM_NAME}")
