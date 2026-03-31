"""Add telegram_username to trainers (for https://t.me/username in Mini App)."""

from alembic import op
import sqlalchemy as sa


revision = "0049_trainer_telegram_username"
down_revision = "0048_client_telegram_username"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("trainers", sa.Column("telegram_username", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_trainers_telegram_username",
        "trainers",
        ["telegram_username"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_trainers_telegram_username", table_name="trainers")
    op.drop_column("trainers", "telegram_username")
