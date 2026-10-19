"""Характеры минских катков для шкалы обычной загрузки (TASK-290).

Решение владельца 2026-10-19 по уликам TASK-290: людные — Замок, Чижовка, Притыцкого,
Немига; тихий — «Юность». DiaMond и Ledlife — обычные (значение по умолчанию, не пишем).
Минск-Арена и Олимпик без слотов — не трогаем. Меняем только ``steady``: правку админа
миграция не затирает.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0244_minsk_load_characters"
down_revision = "0243_city_picks"
branch_labels = None
depends_on = None

_CHARACTERS = {
    "zamok": "hot",
    "chizhovka": "hot",
    "ledby": "hot",
    "katok-na-nemige-u-dvortsa-sporta": "hot",
    "minsk-junost": "quiet",
}

_MINSK_PROFILES = """
    UPDATE arena_profiles p
    SET load_character = :character
    FROM cities c
    WHERE c.id = p.city_id
      AND c.country = 'BY' AND c.name = 'Минск'
      AND p.slug = :slug
      AND p.load_character = :from_character
"""


def upgrade() -> None:
    for slug, character in _CHARACTERS.items():
        op.execute(sa.text(_MINSK_PROFILES).bindparams(character=character, slug=slug, from_character="steady"))


def downgrade() -> None:
    for slug, character in _CHARACTERS.items():
        op.execute(sa.text(_MINSK_PROFILES).bindparams(character="steady", slug=slug, from_character=character))
