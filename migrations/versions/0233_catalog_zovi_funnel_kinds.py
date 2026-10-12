"""TASK-237: invite funnel events in catalog_consumer_events.

Five new ``kind`` values for the «Пойдёшь со мной на каток?» card. The CHECK is
rebuilt as in 0223. Downgrade deletes the new rows first: the old constraint
would refuse to be created over them.

Revision ID: 0233_zovi_funnel_kinds
Revises: 0232_ice_invites
"""

from __future__ import annotations

from alembic import op

revision = "0233_zovi_funnel_kinds"
down_revision = "0232_ice_invites"
branch_labels = None
depends_on = None

_OLD_KINDS = "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', 'public_contact_click'"
_NEW_ONLY = "'invite_create', 'invite_open', 'invite_no_attempt', 'invite_yes', 'invite_send_answer'"
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
