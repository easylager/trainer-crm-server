"""Компания на лёд: событие, сбор, ответы, сообщения бота, напоминания.

Срок хранения строк задаёт приложение (ICE_COMPANY_RETENTION_DAYS, по умолчанию
30) и чистит планировщик. Даунгрейд удаляет таблицы. Новые kind аналитики
добавляются в тот же проход: без них вставка событий каталога отклоняется CHECK.

Revision ID: 0237_ice_companies
Revises: 0236_minsk_arena_coords
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0237_ice_companies"
down_revision = "0236_minsk_arena_coords"
branch_labels = None
depends_on = None

_OLD_KINDS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', "
    "'public_contact_click', 'invite_create', 'invite_open', 'invite_no_attempt', "
    "'invite_yes', 'invite_send_answer'"
)
_NEW_ONLY = (
    "'company_created', 'card_shared', 'company_response', 'company_confirmed', "
    "'repeat_clicked', 'reminder_sent', 'company_unsubscribed', 'bot_blocked', "
    "'company_attended', 'outbound_429'"
)
_KINDS = f"{_OLD_KINDS}, {_NEW_ONLY}"


def upgrade() -> None:
    op.create_table(
        "ice_company_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("venue_ref", sa.String(length=64), nullable=False),
        sa.Column("venue_label", sa.String(length=120), nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_ref", name="uq_ice_company_events_source_ref"),
        sa.CheckConstraint(
            "kind IN ('public_skate', 'open_ice', 'hockey_practice', 'hockey_match')",
            name="ck_ice_company_events_kind",
        ),
        sa.CheckConstraint("version >= 1", name="ck_ice_company_events_version"),
    )
    op.create_table(
        "ice_companies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("public_code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("organizer_ref", sa.String(length=80), nullable=False),
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_company_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("min_people", sa.Integer(), nullable=False),
        sa.Column("max_people", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("weekly_in_chat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("card_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("confirm_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schedule_notice_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cancel_notice_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_code", name="uq_ice_companies_public_code"),
        sa.CheckConstraint(
            "public_code ~ '^[23456789abcdefghjkmnpqrstuvwxyz]{8}$'",
            name="ck_ice_companies_public_code",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'confirmed', 'cancelled', 'expired')",
            name="ck_ice_companies_status",
        ),
        sa.CheckConstraint("min_people BETWEEN 1 AND 30", name="ck_ice_companies_min_people"),
        sa.CheckConstraint(
            "max_people IS NULL OR max_people >= min_people",
            name="ck_ice_companies_max_people",
        ),
        sa.CheckConstraint("char_length(name) <= 40", name="ck_ice_companies_name"),
    )
    op.create_index("ix_ice_companies_organizer_status", "ice_companies", ["organizer_ref", "status"])
    op.create_index("ix_ice_companies_event_id", "ice_companies", ["event_id"])
    op.create_table(
        "ice_company_responses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("attended", sa.Boolean(), nullable=True),
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("needs_reconfirm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("departing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("join_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("company_id", "participant_key", name="uq_ice_company_responses_participant"),
        sa.CheckConstraint("status IN ('going', 'maybe', 'cant')", name="ck_ice_company_responses_status"),
        sa.CheckConstraint("source IN ('tg', 'web', 'viber')", name="ck_ice_company_responses_source"),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 20",
            name="ck_ice_company_responses_name",
        ),
    )
    op.create_index("ix_ice_company_responses_company", "ice_company_responses", ["company_id"])
    op.create_table(
        "ice_company_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chat_id", sa.BigInteger(), nullable=True),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("inline_message_id", sa.String(length=128), nullable=True),
        sa.Column("last_render_hash", sa.String(length=64), nullable=True),
        sa.Column("is_group", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint(
            "inline_message_id IS NOT NULL OR (chat_id IS NOT NULL AND message_id IS NOT NULL)",
            name="ck_ice_company_messages_target",
        ),
    )
    op.create_index("ix_ice_company_messages_company", "ice_company_messages", ["company_id"])
    op.create_table(
        "ice_company_reminders",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "company_id",
            sa.BigInteger(),
            sa.ForeignKey("ice_companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.UniqueConstraint("company_id", "kind", name="uq_ice_company_reminders_kind"),
        sa.CheckConstraint(
            "kind IN ('day', 'hour', 'organizer_followup', 'after', 'weekly')",
            name="ck_ice_company_reminders_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'skipped')",
            name="ck_ice_company_reminders_status",
        ),
    )
    op.create_index("ix_ice_company_reminders_due", "ice_company_reminders", ["status", "due_at"])

    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        f"kind IN ({_KINDS})",
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM catalog_consumer_events WHERE kind IN ({_NEW_ONLY})")
    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        f"kind IN ({_OLD_KINDS})",
    )
    op.drop_index("ix_ice_company_reminders_due", table_name="ice_company_reminders")
    op.drop_table("ice_company_reminders")
    op.drop_index("ix_ice_company_messages_company", table_name="ice_company_messages")
    op.drop_table("ice_company_messages")
    op.drop_index("ix_ice_company_responses_company", table_name="ice_company_responses")
    op.drop_table("ice_company_responses")
    op.drop_index("ix_ice_companies_event_id", table_name="ice_companies")
    op.drop_index("ix_ice_companies_organizer_status", table_name="ice_companies")
    op.drop_table("ice_companies")
    op.drop_table("ice_company_events")
