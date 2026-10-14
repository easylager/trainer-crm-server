"""Минск Арена на карте стояла в километре к западу — у Мястровской, 127.

Точки сверены с OSM (way 292848094 — сама арена, пр-т Победителей 111;
«Конькобежный стадион» — овал южнее неё). Конькобежный стадион до сих пор стоял
на точке арены, поэтому двигаем обоих, иначе пины лягут друг на друга.
Обновляем только старые координаты: ручную правку из админки не перетираем.

Revision ID: 0236_minsk_arena_coords
Revises: 0235_media_display_tone
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0236_minsk_arena_coords"
down_revision = "0235_media_display_tone"
branch_labels = None
depends_on = None

# name, (old lat, old lon), (new lat, new lon)
_FIXES = (
    ("Минск Арена", (53.9394, 27.4685), (53.936071, 27.481615)),
    ("Конькобежный стадион", (53.93593, 27.481638), (53.934798, 27.481877)),
)

_MOVE = sa.text(
    "UPDATE arenas SET latitude = :to_lat, longitude = :to_lon "
    "WHERE name = :name AND latitude = :from_lat AND longitude = :from_lon"
)


def _move(src_index: int, dst_index: int) -> None:
    bind = op.get_bind()
    for name, *points in _FIXES:
        src, dst = points[src_index], points[dst_index]
        bind.execute(
            _MOVE,
            {"name": name, "from_lat": src[0], "from_lon": src[1], "to_lat": dst[0], "to_lon": dst[1]},
        )


def upgrade() -> None:
    _move(0, 1)


def downgrade() -> None:
    _move(1, 0)
