"""Правила типичной загрузки сеансов (TASK-290).

Revision ID: 0239_session_load_rules
Revises: 0238_ice_company_avatars
"""

from __future__ import annotations

from datetime import time

import sqlalchemy as sa
from alembic import op

revision = "0239_session_load_rules"
down_revision = "0238_ice_company_avatars"
branch_labels = None
depends_on = None

_SCOPE = "scope IN ('all', 'character', 'arena')"
_CHARACTER = "character IS NULL OR character IN ('quiet', 'steady', 'hot')"
_ARENA_SCOPE = (
    "(scope = 'all' AND character IS NULL AND arena_id IS NULL) OR "
    "(scope = 'character' AND character IS NOT NULL AND arena_id IS NULL) OR "
    "(scope = 'arena' AND character IS NULL AND arena_id IS NOT NULL)"
)
_DAY = "day_group IN ('mon_thu', 'fri', 'sat', 'sun')"
_LEVEL = "level IN ('calm', 'medium', 'busy')"
_SOURCE = "source IN ('default', 'admin', 'review')"


def upgrade() -> None:
    op.add_column(
        "arena_profiles",
        sa.Column(
            "load_character",
            sa.String(length=16),
            nullable=False,
            server_default="steady",
        ),
    )
    op.create_check_constraint(
        "ck_arena_profiles_load_character",
        "arena_profiles",
        "load_character IN ('quiet', 'steady', 'hot')",
    )

    op.create_table(
        "session_load_rules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("character", sa.String(length=16), nullable=True),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("day_group", sa.String(length=16), nullable=False),
        sa.Column("starts_from", sa.Time(), nullable=False),
        sa.Column("starts_before", sa.Time(), nullable=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="default"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(_SCOPE, name="ck_session_load_rules_scope"),
        sa.CheckConstraint(_CHARACTER, name="ck_session_load_rules_character"),
        sa.CheckConstraint(_ARENA_SCOPE, name="ck_session_load_rules_scope_shape"),
        sa.CheckConstraint(_DAY, name="ck_session_load_rules_day_group"),
        sa.CheckConstraint(_LEVEL, name="ck_session_load_rules_level"),
        sa.CheckConstraint(_SOURCE, name="ck_session_load_rules_source"),
    )
    op.create_index(
        "ix_session_load_rules_lookup",
        "session_load_rules",
        ["scope", "day_group", "arena_id", "character"],
    )

    rules = sa.table(
        "session_load_rules",
        sa.column("scope", sa.String),
        sa.column("character", sa.String),
        sa.column("arena_id", sa.Integer),
        sa.column("day_group", sa.String),
        sa.column("starts_from", sa.Time),
        sa.column("starts_before", sa.Time),
        sa.column("level", sa.String),
        sa.column("source", sa.String),
    )
    seed: list[dict] = []
    for day_group, bands in _DEFAULT_BANDS:
        for starts_from, starts_before, level in bands:
            seed.append(
                {
                    "scope": "all",
                    "character": None,
                    "arena_id": None,
                    "day_group": day_group,
                    "starts_from": starts_from,
                    "starts_before": starts_before,
                    "level": level,
                    "source": "default",
                }
            )
    op.bulk_insert(rules, seed)


_DEFAULT_BANDS: list[tuple[str, list[tuple[time, time | None, str]]]] = [
    (
        "mon_thu",
        [
            (time(0, 0), time(16, 0), "calm"),
            (time(16, 0), time(19, 0), "medium"),
            (time(19, 0), None, "busy"),
        ],
    ),
    (
        "fri",
        [
            (time(0, 0), time(15, 0), "calm"),
            (time(15, 0), time(18, 0), "medium"),
            (time(18, 0), None, "busy"),
        ],
    ),
    (
        "sat",
        [
            (time(0, 0), time(11, 0), "medium"),
            (time(11, 0), time(20, 0), "busy"),
            (time(20, 0), None, "medium"),
        ],
    ),
    (
        "sun",
        [
            (time(0, 0), time(11, 0), "medium"),
            (time(11, 0), time(16, 0), "busy"),
            (time(16, 0), time(19, 0), "medium"),
            (time(19, 0), None, "calm"),
        ],
    ),
]


def downgrade() -> None:
    op.drop_index("ix_session_load_rules_lookup", table_name="session_load_rules")
    op.drop_table("session_load_rules")
    op.drop_constraint("ck_arena_profiles_load_character", "arena_profiles", type_="check")
    op.drop_column("arena_profiles", "load_character")
