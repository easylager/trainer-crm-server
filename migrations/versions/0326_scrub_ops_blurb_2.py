"""Убрать служебные пометки из публичного short_description (TASK-423).

minsk-junost показывал «только по origin junost.by (с не-BY IP страница 403)» —
заметка для разработчиков в «О катке». pinsk-volna — домен в обратных кавычках.

Revision ID: 0326_scrub_ops_blurb_2
Revises: 0325_kk_rescore_notice
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0326_scrub_ops_blurb_2"
down_revision = "0325_kk_rescore_notice"
branch_labels = None
depends_on = None

_FIXES: tuple[tuple[str, str], ...] = (
    ("minsk-junost", "Крытый каток ХК «Юность-Минск», ул. Первомайская, 3."),
    (
        "pinsk-volna",
        "УСК «Волна» / Ледовая арена ПолесГУ, ул. Иркутско-Пинской дивизии, 46. "
        "Массовое катание по недельному расписанию (преимущественно вечерние сеансы), "
        "прокат и заточка коньков. Не путать с клубной ареной «Ястребов» (pinsk.hockey.by).",
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    for slug, description in _FIXES:
        conn.execute(
            text("UPDATE arena_profiles SET short_description = :description WHERE slug = :slug"),
            {"slug": slug, "description": description},
        )


def downgrade() -> None:
    # Ops-фразы в публичное поле не возвращаем.
    pass
