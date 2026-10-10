"""TASK-196: backfill arena_profiles.timezone from the city country.

Валюта и время держались на совпадении «все города BY и UTC+3». Теперь таймзона
арены берётся из её города: BY → Europe/Minsk, RU → Europe/Moscow. Колонка
существовала и раньше (её вручную заполнял админ), меняются только данные: NULL
у арен в известных странах заполняется, остальное не трогается.

Revision ID: 0221_arena_timezone_backfill
Revises: 0220_catalog_consumer_dedup
"""

from __future__ import annotations

from alembic import op

revision = "0221_arena_timezone_backfill"
down_revision = "0220_catalog_consumer_dedup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE arena_profiles p
        SET timezone = CASE c.country
            WHEN 'BY' THEN 'Europe/Minsk'
            WHEN 'RU' THEN 'Europe/Moscow'
        END
        FROM cities c
        WHERE c.id = p.city_id
          AND p.timezone IS NULL
          AND c.country IN ('BY', 'RU')
        """
    )


def downgrade() -> None:
    # До миграции таймзона у всех арен была NULL, поэтому откат возвращает NULL.
    # Совпадающее с минским/московским значение, выставленное админом после
    # upgrade, откат тоже сотрёт — других пар у продукции нет.
    op.execute(
        """
        UPDATE arena_profiles p
        SET timezone = NULL
        FROM cities c
        WHERE c.id = p.city_id
          AND p.timezone IN ('Europe/Minsk', 'Europe/Moscow')
          AND c.country IN ('BY', 'RU')
        """
    )
