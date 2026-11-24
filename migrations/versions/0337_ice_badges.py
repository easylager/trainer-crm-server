"""«Значки» волны 1 и «Серия под угрозой» (TASK-451, флаг redesign_s5).

Revision ID: 0337_ice_badges
Revises: 0336_ice_checkins
Create Date: 2026-11-28

Только добавление:

- ``ice_badges`` — вручённый значок: (telegram_id, profile_id, badge_key, season).
  ``profile_id NULL`` = владелец аккаунта, как в ``ice_checkins``. ``season`` —
  дата начала сезона (1 сентября), чтобы значки прошлых сезонов жили отдельно.
  ``shown_at NULL`` — лист вручения ещё не показывали: bootstrap отдаёт такие
  в ``home.pending_badges``, приложение помечает показанными при открытии листа.
- ``ice_streak_risk_sends`` — дедупликация сообщения бота «Серия под угрозой»:
  одна строка на (telegram_id, понедельник недели) — не чаще раза в неделю.

Откат удаляет обе таблицы.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0337_ice_badges"
down_revision = "0336_ice_checkins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_badges",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column("badge_key", sa.String(24), nullable=False),
        sa.Column("season", sa.Date(), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "badge_key IN ('first_ice','streak_3','streak_5','streak_10','days_10','days_25')",
            name="ck_ice_badges_key",
        ),
    )
    op.create_index(
        "uq_ice_badges_tg_profile_key_season",
        "ice_badges",
        ["telegram_id", sa.text("COALESCE(profile_id, 0)"), "badge_key", "season"],
        unique=True,
    )
    op.create_index(
        "ix_ice_badges_tg_shown",
        "ice_badges",
        ["telegram_id", "shown_at"],
    )

    op.create_table(
        "ice_streak_risk_sends",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("telegram_id", "week_start", name="pk_ice_streak_risk_sends"),
    )


def downgrade() -> None:
    op.drop_table("ice_streak_risk_sends")
    op.drop_index("ix_ice_badges_tg_shown", table_name="ice_badges")
    op.drop_index("uq_ice_badges_tg_profile_key_season", table_name="ice_badges")
    op.drop_table("ice_badges")
