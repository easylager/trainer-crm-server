"""Allow trainer in multiple active collectives (ADR-003 W4)."""

from alembic import op

revision = "0169_collective_multi_w4"
down_revision = "0168_collective_pass_products_w3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_collective_members_one_active_per_trainer")


def downgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_collective_members_one_active_per_trainer
        ON collective_members (trainer_id)
        WHERE status = 'active'
        """
    )
