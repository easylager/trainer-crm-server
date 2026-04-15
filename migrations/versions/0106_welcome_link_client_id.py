"""Optional client_id on welcome_link_tokens (trainer invite: bind Telegram to existing client row)."""

from alembic import op
import sqlalchemy as sa


revision = "0106_welcome_link_client_id"
down_revision = "0105_welcome_link_service_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "welcome_link_tokens",
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_welcome_link_tokens_client_id",
        "welcome_link_tokens",
        ["client_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_welcome_link_tokens_client_id", table_name="welcome_link_tokens")
    op.drop_column("welcome_link_tokens", "client_id")
