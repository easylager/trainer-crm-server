"""ice_ops_alerts: дедупликация операционных алертов льда в БД (TASK-176).

Первый ключ — ``ice_scheduler_stalled`` (сторож «планировщик не делает прогонов»).
Состояние в БД, а не в памяти: рестарт воркера не даёт ни повторного 🔴, ни потери ✅.

Revision ID: 0216_ice_ops_alerts
Revises: 0215_catalog_listed_invite_push
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0216_ice_ops_alerts"
down_revision = "0215_catalog_listed_invite_push"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_ops_alerts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("state", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ice_ops_alerts")
