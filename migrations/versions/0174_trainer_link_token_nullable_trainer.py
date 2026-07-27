"""Landing signup: link token may exist before trainer row (lazy create on Telegram open).

Revision ID: 0174_trainer_link_nullable
Revises: 0173_booking_party_notifications
"""
from alembic import op
import sqlalchemy as sa


revision = "0174_trainer_link_nullable"
down_revision = "0173_booking_party_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "trainer_link_tokens",
        "trainer_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "trainer_link_tokens",
        "trainer_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
