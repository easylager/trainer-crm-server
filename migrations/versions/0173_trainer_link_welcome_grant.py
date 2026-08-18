"""Store optional prepaid subscription on trainer welcome-link tokens."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0173_trainer_link_welcome_grant"
down_revision = "0172_canonical_org_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_link_tokens",
        sa.Column("welcome_grant_kind", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "trainer_link_tokens",
        sa.Column("welcome_grant_modules", JSONB(), nullable=True),
    )
    op.add_column(
        "trainer_link_tokens",
        sa.Column("welcome_grant_period_months", sa.Integer(), nullable=True),
    )
    op.add_column(
        "trainer_link_tokens",
        sa.Column("welcome_grant_admin_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "trainer_link_tokens",
        sa.Column("welcome_grant_applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_link_tokens", "welcome_grant_applied_at")
    op.drop_column("trainer_link_tokens", "welcome_grant_admin_id")
    op.drop_column("trainer_link_tokens", "welcome_grant_period_months")
    op.drop_column("trainer_link_tokens", "welcome_grant_modules")
    op.drop_column("trainer_link_tokens", "welcome_grant_kind")
