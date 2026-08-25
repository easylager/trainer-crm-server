"""Care pulses: silence-aware presence check-ins for trainers and clients.

Revision ID: 0176_care_pulses
Revises: 0175_merge_link_heads
"""

from alembic import op
import sqlalchemy as sa


revision = "0176_care_pulses"
down_revision = "0175_merge_link_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "care_pulses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("context_key", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audience",
            "recipient_id",
            "kind",
            "context_key",
            name="uq_care_pulses_audience_recipient_kind_ctx",
        ),
    )
    op.create_index(
        "ix_care_pulses_audience_recipient_sent",
        "care_pulses",
        ["audience", "recipient_id", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_care_pulses_audience_recipient_sent", table_name="care_pulses")
    op.drop_table("care_pulses")
