"""ice_parser_jobs: per-arena parser schedule (TASK-071).

Revision ID: 0196_ice_parser_jobs
Revises: 0195_trainer_arenas_is_public
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0196_ice_parser_jobs"
down_revision = "0195_trainer_arenas_is_public"
branch_labels = None
depends_on = None

_MINSK_ARENA_CONFIG = {
    "url": "https://saleframe.minskarena.by/service/55",
    "api_host": "https://abws.minskarena.by",
    "service_id": 55,
    "init_path": "/api/v3/frame/init",
    "init_query": {"seid": 55, "target": "saleframe", "lang": "ru"},
    "calendar_path": "/api/v1/frame/service/{service_id}/calendar",
    "events_path": "/api/v1/frame/service/{service_id}/events",
    "events_query": {
        "sort": "start",
        "expand": "prices",
        "fields": "id,start,end,quota",
        "target": "saleframe",
        "lang": "ru",
    },
    "timezone": "Europe/Minsk",
    "default_duration_minutes": 45,
    "prices_already_minor": True,
    "adult_zone_id": 970,
    "child_zone_id": 971,
    "kind": "public_skate",
    "kind_allow_substrings": ["массовое катание"],
    "drop_item_name_substrings": ["заточка"],
    "requires_by_egress": False,
    "requires_auth": False,
}


def upgrade() -> None:
    op.create_table(
        "ice_parser_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "arena_id",
            sa.Integer(),
            sa.ForeignKey("arenas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parser_key", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("arena_id", name="uq_ice_parser_jobs_arena_id"),
        sa.CheckConstraint(
            "cadence IN ('hourly', 'daily', 'weekly')",
            name="ck_ice_parser_jobs_cadence",
        ),
    )
    op.create_index(
        "ix_ice_parser_jobs_due",
        "ice_parser_jobs",
        ["is_enabled", "next_run_at"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO ice_parser_jobs (
                arena_id, parser_key, is_enabled, cadence, next_run_at, config, notes
            )
            SELECT
                arena.id,
                'minskarena_saleframe_v1',
                true,
                'daily',
                now(),
                CAST(:config AS jsonb),
                'TASK-071 seed: Minsk Arena saleframe/55'
            FROM arenas AS arena
            LEFT JOIN arena_profiles AS profile ON profile.arena_id = arena.id
            WHERE profile.slug = 'minskarena'
               OR lower(arena.name) IN ('минск-арена', 'минск арена')
            ORDER BY CASE WHEN profile.slug = 'minskarena' THEN 0 ELSE 1 END, arena.id
            LIMIT 1
            ON CONFLICT (arena_id) DO NOTHING
            """
        ).bindparams(sa.bindparam("config", json.dumps(_MINSK_ARENA_CONFIG, ensure_ascii=False)))
    )


def downgrade() -> None:
    op.drop_index("ix_ice_parser_jobs_due", table_name="ice_parser_jobs")
    op.drop_table("ice_parser_jobs")
