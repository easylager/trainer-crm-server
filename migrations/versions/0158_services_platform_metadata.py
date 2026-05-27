"""Additive platform metadata on catalog services (multi-sport readiness, ice default)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0158_services_platform_meta"
down_revision = "0157_pass_instance_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("slug", sa.String(64), nullable=True))
    op.add_column("services", sa.Column("vertical_key", sa.String(32), nullable=True))
    op.add_column("services", sa.Column("effort_profile", sa.String(32), nullable=True))
    op.add_column("services", sa.Column("scenario_tags", JSONB(), nullable=True))
    op.execute(
        """
        UPDATE services
           SET vertical_key = COALESCE(vertical_key, 'ice'),
               effort_profile = COALESCE(effort_profile, 'default')
         WHERE vertical_key IS NULL OR effort_profile IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("services", "scenario_tags")
    op.drop_column("services", "effort_profile")
    op.drop_column("services", "vertical_key")
    op.drop_column("services", "slug")
