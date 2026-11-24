"""«Я здесь» — отметки о льде и загрузка катков (TASK-446, флаг redesign_s5).

Revision ID: 0336_ice_checkins
Revises: 0335_kk_evening_boards
Create Date: 2026-11-24

Только добавление:

- ``ice_checkins`` — отметка «Я здесь» на сеанс (приложение / чат-бот / QR-стойка).
  Одна на (telegram_id, профиль, сеанс); ``profile_id NULL`` = владелец аккаунта.
  ``load_level`` 1..3 — единственная оценка «сколько народу», ставится один раз.
  ``counts_for_load`` — аккаунт старше 7 дней на момент вставки: в загрузку катка
  идут только такие оценки, в серию — все.
- ``ice_checkin_prompts`` — вопрос бота «Ты на катке?»: по строке на (telegram_id,
  сеанс), не чаще раза в сутки и по правилам кандидатов (intent / home arena /
  регулярный ритм).
- ``ice_checkin_intents`` — «интерес к сеансу сегодня»: открыл (view) или жал
  «Маршрут» (route). Пишет Mini App; по нему бот понимает, кого спросить.
- ``ice_checkin_mutes`` — два «Я не на катке» подряд по катку → не пишем 30 дней;
  успешная отметка на катке сбрасывает серию.
- ``ice_checkin_helps`` — «помог выбрать время» (этап 5.2): чужой просмотр сеанса,
  у которого была свежая засчитанная оценка докладчика. Таблица создаётся сейчас,
  писать начнём в 5.2.

Откат удаляет все пять таблиц.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0336_ice_checkins"
down_revision = "0335_kk_evening_boards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ice_checkins",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("ice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("load_level", sa.SmallInteger(), nullable=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("counts_for_load", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("load_set_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("load_level BETWEEN 1 AND 3", name="ck_ice_checkins_load_level"),
        sa.CheckConstraint("source IN ('app','chat','qr')", name="ck_ice_checkins_source"),
    )
    op.create_index(
        "uq_ice_checkins_tg_profile_session",
        "ice_checkins",
        ["telegram_id", sa.text("COALESCE(profile_id, 0)"), "session_id"],
        unique=True,
    )
    op.create_index("ix_ice_checkins_session_created", "ice_checkins", ["session_id", "created_at"])
    op.create_index("ix_ice_checkins_tg_date", "ice_checkins", ["telegram_id", "local_date"])
    op.create_index("ix_ice_checkins_arena_created", "ice_checkins", ["arena_id", "created_at"])

    op.create_table(
        "ice_checkin_prompts",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("ice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(8), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "reason IN ('intent','home','regular')", name="ck_ice_checkin_prompts_reason"
        ),
        sa.CheckConstraint(
            "status IN ('pending','sent','answered','not_here','expired','skipped')",
            name="ck_ice_checkin_prompts_status",
        ),
        sa.UniqueConstraint("telegram_id", "session_id", name="uq_ice_checkin_prompts_tg_session"),
    )
    op.create_index("ix_ice_checkin_prompts_status_due", "ice_checkin_prompts", ["status", "due_at"])

    op.create_table(
        "ice_checkin_intents",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("ice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('view','route')", name="ck_ice_checkin_intents_kind"),
        sa.UniqueConstraint("telegram_id", "session_id", "kind", name="uq_ice_checkin_intents_tg_session_kind"),
    )

    op.create_table(
        "ice_checkin_mutes",
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("not_here_streak", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("telegram_id", "arena_id", name="pk_ice_checkin_mutes"),
    )

    op.create_table(
        "ice_checkin_helps",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("reporter_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("viewer_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("ice_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "reporter_telegram_id", "viewer_telegram_id", "session_id", name="uq_ice_checkin_helps"
        ),
    )


def downgrade() -> None:
    op.drop_table("ice_checkin_helps")
    op.drop_table("ice_checkin_mutes")
    op.drop_table("ice_checkin_intents")
    op.drop_index("ix_ice_checkin_prompts_status_due", table_name="ice_checkin_prompts")
    op.drop_table("ice_checkin_prompts")
    op.drop_index("ix_ice_checkins_arena_created", table_name="ice_checkins")
    op.drop_index("ix_ice_checkins_tg_date", table_name="ice_checkins")
    op.drop_index("ix_ice_checkins_session_created", table_name="ice_checkins")
    op.drop_index("uq_ice_checkins_tg_profile_session", table_name="ice_checkins")
    op.drop_table("ice_checkins")
