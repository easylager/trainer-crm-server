"""TASK-179: schedule_basis on ice_sessions (live / projected / photo / manual).

Основание сеанса: ``live`` — снято с сайта/API на дату; ``projected`` — регулярная сетка
без подтверждения на дату; ``photo`` — распознано с фото/поста; ``manual`` — внесено нами
(админка ``source_id='admin'`` и эталонные карточки ``etalon_*``).

Backfill: ручные/эталонные → ``manual``; сеансы парсеров, которые не снимают расписание
на дату (Брест, Замок → ``projected``; Лида, подпись Instagram Юности → ``photo``), —
по включённому заданию арены. Следующий прогон парсера всё равно перепишет основание
своих строк из ``Extraction``/конфига.

Revision ID: 0218_ice_sessions_schedule_basis
Revises: 0217_catalog_prod_hygiene
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0218_ice_sessions_schedule_basis"
down_revision = "0217_catalog_prod_hygiene"
branch_labels = None
depends_on = None

_BASIS_CHECK = "schedule_basis IN ('live', 'projected', 'photo', 'manual')"

_PROJECTED_KEYS = ("brest_lds_v1", "zamok_html_v1")
_PHOTO_KEYS = ("lida_lds_v1", "junost_instagram_caption_v1")


def _backfill_by_parser(basis: str, keys: tuple[str, ...]) -> None:
    op.execute(
        sa.text(
            """
            UPDATE ice_sessions s
            SET schedule_basis = :basis
            FROM ice_parser_jobs j
            WHERE j.arena_id = s.arena_id
              AND j.is_enabled
              AND j.parser_key = ANY(:keys)
              AND s.kind IN ('public_skate', 'open_ice')
              AND s.schedule_basis = 'live'
              AND (s.source_id IS NULL OR (s.source_id <> 'admin' AND s.source_id NOT LIKE 'etalon_%'))
            """
        ).bindparams(basis=basis, keys=list(keys))
    )


def upgrade() -> None:
    op.add_column(
        "ice_sessions",
        sa.Column(
            "schedule_basis",
            sa.String(length=16),
            nullable=False,
            server_default="live",
        ),
    )
    op.create_check_constraint("ck_ice_sessions_schedule_basis", "ice_sessions", _BASIS_CHECK)
    op.execute(
        """
        UPDATE ice_sessions
        SET schedule_basis = 'manual'
        WHERE source_id = 'admin' OR source_id LIKE 'etalon_%'
        """
    )
    _backfill_by_parser("projected", _PROJECTED_KEYS)
    _backfill_by_parser("photo", _PHOTO_KEYS)


def downgrade() -> None:
    op.drop_constraint("ck_ice_sessions_schedule_basis", "ice_sessions", type_="check")
    op.drop_column("ice_sessions", "schedule_basis")
