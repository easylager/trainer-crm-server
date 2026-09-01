"""«Не сейчас» на приглашении в каталог переезжает из localStorage в БД.

The hub's catalog invite had a secondary «Не сейчас» whose only memory was
``localStorage``: it was forgotten on another device, in another Telegram client, or
after a cache clear — so a trainer who declined kept being asked. A refusal is an
answer and has to be stored where the answer to it is computed.

Revision ID: 0183_catalog_dismiss
Revises: 0182_catalog_opt_in
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0183_catalog_dismiss"
down_revision = "0182_catalog_opt_in"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "trainer_profiles",
        sa.Column("catalog_invite_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("trainer_profiles", "catalog_invite_dismissed_at")
