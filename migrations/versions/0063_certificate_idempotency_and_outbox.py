"""Certificate issue idempotency, email_sent_at, and outbox for failed sends."""

from alembic import op
import sqlalchemy as sa


revision = "0063_certificate_outbox"
down_revision = "0062_pass_instance_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificate_instances",
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"], unique=False)
    op.create_table(
        "certificate_email_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("certificate_id", sa.Integer(), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["certificate_id"], ["certificate_instances.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_certificate_email_outbox_status", "certificate_email_outbox", ["status"], unique=False)
    op.create_index("ix_certificate_email_outbox_certificate_id", "certificate_email_outbox", ["certificate_id"], unique=False)
    op.create_index(
        "uq_certificate_email_outbox_pending",
        "certificate_email_outbox",
        ["certificate_id", "to_email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_certificate_email_outbox_pending", table_name="certificate_email_outbox", postgresql_where=sa.text("status = 'pending'"))
    op.drop_index("ix_certificate_email_outbox_certificate_id", table_name="certificate_email_outbox")
    op.drop_index("ix_certificate_email_outbox_status", table_name="certificate_email_outbox")
    op.drop_table("certificate_email_outbox")
    op.drop_index("ix_idempotency_keys_created_at", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
    op.drop_column("certificate_instances", "email_sent_at")
