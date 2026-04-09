"""Trainer profile: opt-in for group classes (schedule capacity > 1)."""

from alembic import op
import sqlalchemy as sa


revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column(
            "group_classes_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    # Keep server default so INSERTs that omit the column (e.g. tests) get false.


def downgrade() -> None:
    op.drop_column("trainer_profiles", "group_classes_enabled")
