"""Убрать ops-заметки из публичного short_description (Лида и др.).

В досье в «О катке» уехала внутренняя фраза про HTML-таблицу / фото расписания —
её видели все на place page. Чистим строки в БД; runtime-скруббер режет такие
фразы и на старых копиях.

Revision ID: 0324_scrub_ops_short_descriptions
Revises: 0323_watch_stays_on
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0324_scrub_ops_short_descriptions"
down_revision = "0323_watch_stays_on"
branch_labels = None
depends_on = None

# slug → публичный текст (без парсерских пометок). Downgrade не восстанавливает ops-мусор.
_FIXES: tuple[tuple[str, str], ...] = (
    (
        "lida-lds",
        "Ледовый дворец ГУ «Клуб по хоккею с шайбой «Лида», ул. Качана, 31.",
    ),
    (
        "orsha-arena",
        "Ледовая арена в составе спорткомплекса ХК «Локомотив-Орша» (наряду с залом «Олимпиец»).",
    ),
    (
        "ostrovets-lds",
        "Ледовая площадка при СДЮШОР. Расписание массового катания обновляется еженедельно на сайте.",
    ),
    (
        "bereza-lds",
        "Ледовая арена (Ледовый дворец спорта) г. Берёза, ул. 17 Сентября, 39. "
        "Построена в 2009, вместимость 570. Расписание массового катания — в Instagram арены.",
    ),
)


def upgrade() -> None:
    conn = op.get_bind()
    for slug, description in _FIXES:
        conn.execute(
            text(
                """
                UPDATE arena_profiles
                SET short_description = :description
                WHERE slug = :slug
                """
            ),
            {"slug": slug, "description": description},
        )


def downgrade() -> None:
    # Ops-фразы в публичное поле не возвращаем.
    pass
