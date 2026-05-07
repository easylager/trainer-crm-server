"""Trainer–client relay chat via bots (fallback when Telegram DM unavailable).

Revision ID: 0145_trainer_client_relay_sessions
Revises: 0144_trainer_services_ui_accent
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0145_trainer_client_relay_sessions"
down_revision = "0144_trainer_services_ui_accent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainer_client_relay_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trainer_id", sa.Integer(), sa.ForeignKey("trainers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="open",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trainer_client_relay_sessions_trainer_id", "trainer_client_relay_sessions", ["trainer_id"])
    op.create_index("ix_trainer_client_relay_sessions_client_id", "trainer_client_relay_sessions", ["client_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_trainer_client_relay_open_pair "
        "ON trainer_client_relay_sessions (trainer_id, client_id) "
        "WHERE status = 'open'"
    )

    op.create_table(
        "trainer_client_relay_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("trainer_client_relay_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sender_role", sa.String(length=16), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trainer_client_relay_messages_session_id",
        "trainer_client_relay_messages",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_trainer_client_relay_messages_session_id", table_name="trainer_client_relay_messages")
    op.drop_table("trainer_client_relay_messages")
    op.execute("DROP INDEX IF EXISTS uq_trainer_client_relay_open_pair")
    op.drop_index("ix_trainer_client_relay_sessions_client_id", table_name="trainer_client_relay_sessions")
    op.drop_index("ix_trainer_client_relay_sessions_trainer_id", table_name="trainer_client_relay_sessions")
    op.drop_table("trainer_client_relay_sessions")
