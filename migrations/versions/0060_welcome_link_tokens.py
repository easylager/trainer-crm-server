"""One-time tokens for welcome links (cert, pass, generic). Token burned on first use."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0060_welcome_link_tokens"
down_revision = "0059_certificate_recipient_phone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "welcome_link_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cert_code", sa.String(32), nullable=True),
        sa.Column("pass_product_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_welcome_link_tokens_trainer_id", "welcome_link_tokens", ["trainer_id"])
    op.create_index("ix_welcome_link_tokens_used_at", "welcome_link_tokens", ["used_at"])


def downgrade() -> None:
    op.drop_index("ix_welcome_link_tokens_used_at", table_name="welcome_link_tokens")
    op.drop_index("ix_welcome_link_tokens_trainer_id", table_name="welcome_link_tokens")
    op.drop_table("welcome_link_tokens")
