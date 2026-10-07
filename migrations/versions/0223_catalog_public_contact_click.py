"""TASK-191-B: demand clicks (phone / tickets / route) from public SSR pages.

Revision ID: 0223_public_contact_click
Revises: 0222_arena_schedule_mode
"""

from __future__ import annotations

from alembic import op

revision = "0223_public_contact_click"
down_revision = "0222_arena_schedule_mode"
branch_labels = None
depends_on = None

_KINDS = (
    "'public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry', 'public_contact_click'"
)


def upgrade() -> None:
    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        f"kind IN ({_KINDS})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_catalog_consumer_events_kind", "catalog_consumer_events", type_="check")
    op.create_check_constraint(
        "ck_catalog_consumer_events_kind",
        "catalog_consumer_events",
        "kind IN ('public_page_view', 'public_telegram_cta', 'miniapp_catalog_entry')",
    )
