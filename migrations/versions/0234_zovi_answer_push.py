"""Ответ на открытку доходит до того, кто позвал: пуш от клиентского бота.

* ``ice_invites.creator_telegram_id`` — Telegram id создателя, если открытку собрали
  в Mini App. Без него пуша нет: создатель смотрит ответ на странице статуса.
* ``ice_invite_answers.notified_at`` / ``notify_claimed_at`` / ``notify_attempts`` —
  захват и повтор доставки: сразу после ответа и из цикла уведомлений бота.

Revision ID: 0234_zovi_answer_push
Revises: 0233_zovi_funnel_kinds
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0234_zovi_answer_push"
down_revision = "0233_zovi_funnel_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ice_invites", sa.Column("creator_telegram_id", sa.BigInteger(), nullable=True))
    op.add_column("ice_invite_answers", sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ice_invite_answers", sa.Column("notify_claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ice_invite_answers",
        sa.Column("notify_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_ice_invite_answers_notify_attempts",
        "ice_invite_answers",
        "notify_attempts BETWEEN 0 AND 20",
    )
    op.create_index(
        "ix_ice_invite_answers_unnotified",
        "ice_invite_answers",
        ["answered_at"],
        postgresql_where=sa.text("notified_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_ice_invite_answers_unnotified", table_name="ice_invite_answers")
    op.drop_constraint("ck_ice_invite_answers_notify_attempts", "ice_invite_answers", type_="check")
    op.drop_column("ice_invite_answers", "notify_attempts")
    op.drop_column("ice_invite_answers", "notify_claimed_at")
    op.drop_column("ice_invite_answers", "notified_at")
    op.drop_column("ice_invites", "creator_telegram_id")
