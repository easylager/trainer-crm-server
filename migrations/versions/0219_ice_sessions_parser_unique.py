"""TASK-187: unique parser-owned slot per (arena, start, kind).

Сначала чистка дублей: из каждой группы строк парсера с одинаковыми
``(arena_id, starts_at_utc, kind)`` остаётся самая свежая (``observed_at`` desc,
затем ``id`` desc), остальные удаляются. Потом — частичный уникальный индекс
только для строк парсера: ручные (``admin``) и эталонные (``etalon_*``) строки
могут совпадать по началу с парсерными и между собой, как раньше.

Прод 2026-10-06 (read-only проверка перед выкатом): 1460 строк парсера, дублей 0.

Downgrade убирает индекс; удалённые дубли не восстанавливаются (это мусор).

Revision ID: 0219_ice_sessions_parser_unique
Revises: 0218_ice_sessions_schedule_basis
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0219_ice_sessions_parser_unique"
down_revision = "0218_ice_sessions_schedule_basis"
branch_labels = None
depends_on = None

_PARSER_ROW = "source_id IS NOT NULL AND source_id <> 'admin' AND source_id NOT LIKE 'etalon_%'"


def upgrade() -> None:
    op.execute(
        f"""
        DELETE FROM ice_sessions s
        USING (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY arena_id, starts_at_utc, kind
                       ORDER BY observed_at DESC NULLS LAST, id DESC
                   ) AS rn
            FROM ice_sessions
            WHERE {_PARSER_ROW}
        ) d
        WHERE s.id = d.id AND d.rn > 1
        """
    )
    op.create_index(
        "uq_ice_sessions_parser_slot",
        "ice_sessions",
        ["arena_id", "starts_at_utc", "kind"],
        unique=True,
        postgresql_where=sa.text(_PARSER_ROW),
    )


def downgrade() -> None:
    op.drop_index("uq_ice_sessions_parser_slot", table_name="ice_sessions")
