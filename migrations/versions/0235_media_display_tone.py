"""Тон фото на сайте: менеджер отмечает кадр, который показываем в одну краску.

По умолчанию false — цветное фото. Ширину и «фасад» сюда не пишем: это решение человека.

Revision ID: 0235_media_display_tone
Revises: 0234_zovi_answer_push
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0235_media_display_tone"
down_revision = "0234_zovi_answer_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media",
        sa.Column("display_tone", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("media", "display_tone")
