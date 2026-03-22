"""Add support_messages table for client/trainer support tickets."""

from alembic import op
import sqlalchemy as sa


revision = "0051_support_messages"
down_revision = "0050_bookings_service_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("from_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("from_role", sa.String(16), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("admin_reply_text", sa.Text(), nullable=True),
        sa.Column("admin_replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_support_messages_from_telegram_id", "support_messages", ["from_telegram_id"], unique=False)
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_support_messages_created_at", table_name="support_messages")
    op.drop_index("ix_support_messages_from_telegram_id", table_name="support_messages")
    op.drop_table("support_messages")
