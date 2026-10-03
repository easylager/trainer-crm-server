"""Клики по маркетинговой ссылке каталога /go/<источник> и шеринг подборки (TASK-146).

Одна строка — один переход по ссылке (до Telegram). Источник — метка из ссылки
(«insta», «flyer-olimpik»): по ней видно, какой канал приводит людей в каталог.
Кто перешёл, не храним — только когда, откуда и в какой город.

Revision ID: 0210_catalog_entry_clicks
Revises: 0209_profile_updated_at
"""

import sqlalchemy as sa
from alembic import op

revision = "0210_catalog_entry_clicks"
down_revision = "0209_profile_updated_at"
branch_labels = None
depends_on = None


_SHARE_KINDS_NEW = "('ice_city_day', 'trainer', 'place', 'selection')"
_SHARE_KINDS_OLD = "('ice_city_day', 'trainer', 'place')"


def upgrade() -> None:
    # «Поделиться подборкой» из каталога: город + тип места + окно времени (/c/{город}).
    op.drop_constraint("ck_client_share_events_kind", "client_share_events", type_="check")
    op.create_check_constraint("ck_client_share_events_kind", "client_share_events", f"kind IN {_SHARE_KINDS_NEW}")
    op.create_table(
        "catalog_entry_clicks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True),
        # Куда увела ссылка: startapp (сразу мини-апп) | bot (кнопка в боте) | web (без бота).
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("referer_host", sa.String(length=120), nullable=True),
    )
    op.create_index("ix_catalog_entry_clicks_source_occurred", "catalog_entry_clicks", ["source", "occurred_at"])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE client_share_events IN ACCESS EXCLUSIVE MODE"))
    has_selection_events = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM client_share_events WHERE kind = 'selection')")
    ).scalar_one()
    if has_selection_events:
        raise RuntimeError(
            "Cannot downgrade 0210_catalog_entry_clicks: client_share_events contains "
            "kind='selection' rows; refusing to narrow the check and discard append-only history."
        )

    op.drop_index("ix_catalog_entry_clicks_source_occurred", table_name="catalog_entry_clicks")
    op.drop_table("catalog_entry_clicks")
    op.drop_constraint("ck_client_share_events_kind", "client_share_events", type_="check")
    op.create_check_constraint("ck_client_share_events_kind", "client_share_events", f"kind IN {_SHARE_KINDS_OLD}")
