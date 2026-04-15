"""Optional service_id on welcome_link_tokens (generic invite: preselect catalog service)."""

from alembic import op
import sqlalchemy as sa


revision = "0105_welcome_link_service_id"
down_revision = "0104_trainer_schedule_grid_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "welcome_link_tokens",
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("services.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("welcome_link_tokens", "service_id")
