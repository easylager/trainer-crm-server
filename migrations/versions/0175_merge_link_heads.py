"""Merge parallel heads: welcome-link grant columns + booking-party / nullable trainer_id chain."""

from alembic import op

revision = "0175_merge_link_heads"
down_revision = ("0173_trainer_link_welcome_grant", "0174_trainer_link_nullable")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
