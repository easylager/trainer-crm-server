"""Arena catalog profiles 1:1 with arenas (TASK-048).

Vitrine fields (slug, district, hours, amenities, publication status) live here so
the trainer-workplace dictionary on ``arenas`` stays unchanged. ``status`` is Ice
Discovery publication (draft|published|archived) — not ``arenas.is_confirmed``
(moderation of trainer-created workplaces, TASK-046).

Revision ID: 0192_arena_profiles
Revises: 0191_by_small_city_discount
"""
from __future__ import annotations

import re

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0192_arena_profiles"
down_revision = "0191_by_small_city_discount"
branch_labels = None
depends_on = None

_CYRILLIC_TO_LATIN = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def _slugify(name: str) -> str:
    raw = (name or "").strip().lower()
    chars: list[str] = []
    for ch in raw:
        if ch in _CYRILLIC_TO_LATIN:
            chars.append(_CYRILLIC_TO_LATIN[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            chars.append(ch)
        else:
            chars.append("-")
    slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
    return slug or "arena"


def _choose_slug(base: str, taken: set[str], arena_id: int) -> str:
    if base not in taken:
        return base
    with_id = f"{base}-{int(arena_id)}"
    if with_id not in taken:
        return with_id
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def upgrade() -> None:
    op.create_table(
        "arena_profiles",
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "city_id",
            sa.Integer(),
            sa.ForeignKey("cities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("district", sa.String(length=128), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("short_description", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("website_url", sa.String(length=512), nullable=True),
        sa.Column("social_urls", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("opening_hours", JSONB(), nullable=True),
        sa.Column("season_start_month", sa.SmallInteger(), nullable=True),
        sa.Column("season_end_month", sa.SmallInteger(), nullable=True),
        sa.Column("amenities", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="published"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by_admin_id", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("city_id", "slug", name="uq_arena_profiles_city_slug"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_arena_profiles_status",
        ),
        sa.CheckConstraint(
            "season_start_month IS NULL OR (season_start_month >= 1 AND season_start_month <= 12)",
            name="ck_arena_profiles_season_start",
        ),
        sa.CheckConstraint(
            "season_end_month IS NULL OR (season_end_month >= 1 AND season_end_month <= 12)",
            name="ck_arena_profiles_season_end",
        ),
    )
    op.create_index("ix_arena_profiles_city_id", "arena_profiles", ["city_id"])
    op.create_index("ix_arena_profiles_status", "arena_profiles", ["status"])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, city_id, name FROM arenas ORDER BY id")).fetchall()
    taken: dict[int, set[str]] = {}
    for arena_id, city_id, name in rows:
        city_taken = taken.setdefault(int(city_id), set())
        slug = _choose_slug(_slugify(str(name or "")), city_taken, int(arena_id))
        city_taken.add(slug)
        conn.execute(
            sa.text(
                """
                INSERT INTO arena_profiles (arena_id, city_id, slug, status)
                VALUES (:arena_id, :city_id, :slug, 'published')
                """
            ),
            {"arena_id": int(arena_id), "city_id": int(city_id), "slug": slug},
        )


def downgrade() -> None:
    op.drop_index("ix_arena_profiles_status", table_name="arena_profiles")
    op.drop_index("ix_arena_profiles_city_id", table_name="arena_profiles")
    op.drop_table("arena_profiles")
