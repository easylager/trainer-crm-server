"""Trainers and one-time link tokens for Telegram binding.

Revision ID: 0002_trainers
Revises: 0001_initial
Create Date: trainer_link_tokens

"""
from alembic import op
import sqlalchemy as sa


revision = "0002_trainers"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trainers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_trainers_telegram_id"), "trainers", ["telegram_id"], unique=True)

    op.create_table(
        "trainer_link_tokens",
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("trainer_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["trainer_id"], ["trainers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token"),
    )


def downgrade() -> None:
    op.drop_table("trainer_link_tokens")
    op.drop_index(op.f("ix_trainers_telegram_id"), table_name="trainers")
    op.drop_table("trainers")
