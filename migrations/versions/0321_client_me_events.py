"""Вкладка «Я»: три kind аналитики (TASK-368).

CHECK на ``catalog_consumer_events.kind`` иначе отклоняет вставку. Список прежний
плюс ``me_open``, ``me_name_set``, ``me_home_arena_set``.

Revision ID: 0321_client_me_events
Revises: 0320_client_account_season
"""

from __future__ import annotations

from alembic import op

revision = "0321_client_me_events"
down_revision = "0320_client_account_season"
branch_labels = None
depends_on = None

_OLD_KINDS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', "
    "'public_contact_click', 'invite_create', 'invite_open', 'invite_no_attempt', "
    "'invite_yes', 'invite_send_answer', 'company_created', 'card_shared', "
    "'company_response', 'company_confirmed', 'repeat_clicked', 'reminder_sent', "
    "'company_unsubscribed', 'bot_blocked', 'company_attended', 'outbound_429'"
)
_NEW_ONLY = "'me_open', 'me_name_set', 'me_home_arena_set'"
_KINDS = f"{_OLD_KINDS}, {_NEW_ONLY}"


def upgrade() -> None:
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
