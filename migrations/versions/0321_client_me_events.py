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


_TABLE = "catalog_consumer_events"
_CK = "ck_catalog_consumer_events_kind"


def _replace_check(kinds: str) -> None:
    """Пересоздать CHECK без долгого ACCESS EXCLUSIVE: NOT VALID (без скана), затем отдельный VALIDATE."""
    op.drop_constraint(_CK, _TABLE, type_="check")
    op.execute(f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CK} CHECK (kind IN ({kinds})) NOT VALID")
    op.execute(f"ALTER TABLE {_TABLE} VALIDATE CONSTRAINT {_CK}")


def upgrade() -> None:
    _replace_check(_KINDS)


def downgrade() -> None:
    """ВНИМАНИЕ: строки новых kind (me_open, me_name_set, me_home_arena_set) удаляются безвозвратно.

    Без этого старый CHECK не пересоздать: существующие строки его нарушают.
    """
    op.execute(f"DELETE FROM {_TABLE} WHERE kind IN ({_NEW_ONLY})")
    _replace_check(_OLD_KINDS)
