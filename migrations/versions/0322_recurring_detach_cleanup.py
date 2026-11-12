"""Снятие постоянного клиента без мусора (TASK-396).

``slots.created_for_recurring_client_slot_id`` — окно, которое цикл автозаписи создал сам
(не переиспользовал окно тренера). При снятии правила и обрезке за горизонтом такое окно
удаляется, если на нём не осталось активных записей. SET NULL: правило удаляется только
каскадом вместе с клиентом/тренером, и тогда окно просто теряет метку.

``recurring_client_slots.client_notice_queued_at / client_notice_sent_at`` — одно сообщение
клиенту «постоянное время снято»: строка правила сама служит очередью (одно правило — одно
сообщение), её дренирует цикл уведомлений об отмене.

Revision ID: 0322_recurring_detach_cleanup
Revises: 0321_client_me_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0322_recurring_detach_cleanup"
down_revision = "0321_client_me_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "slots",
        sa.Column(
            "created_for_recurring_client_slot_id",
            sa.Integer(),
            sa.ForeignKey(
                "recurring_client_slots.id",
                ondelete="SET NULL",
                name="fk_slots_created_for_recurring_client_slot_id",
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_slots_created_for_recurring_client_slot_id",
        "slots",
        ["created_for_recurring_client_slot_id"],
        postgresql_where=sa.text("created_for_recurring_client_slot_id IS NOT NULL"),
    )
    op.add_column(
        "recurring_client_slots",
        sa.Column("client_notice_queued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "recurring_client_slots",
        sa.Column("client_notice_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recurring_client_slots", "client_notice_sent_at")
    op.drop_column("recurring_client_slots", "client_notice_queued_at")
    op.drop_index("ix_slots_created_for_recurring_client_slot_id", table_name="slots")
    op.drop_constraint(
        "fk_slots_created_for_recurring_client_slot_id", "slots", type_="foreignkey"
    )
    op.drop_column("slots", "created_for_recurring_client_slot_id")
