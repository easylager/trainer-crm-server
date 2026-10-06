"""TASK-205: create_mozyr_global_ice.py — idempotent, does not touch arena id=44."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from scripts.create_mozyr_global_ice import (
    ARENA_NAME,
    CITY_NAME,
    PARSER_KEY_WEEKLY_GRID_V1,
    SLUG,
    apply_mozyr_global_ice,
    provision,
)
from src.shared.config import Settings


def _sync_url() -> str:
    url = Settings().database_url_sync or Settings().database_url
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def test_dry_run_does_not_write() -> None:
    result = provision(apply=False)
    assert result.city_id == 0
    assert result.arena_id == 0
    assert not result.created_city


def test_apply_creates_and_second_run_is_idempotent() -> None:
    engine = create_engine(_sync_url())
    with Session(engine) as session:
        trans = session.begin()
        try:
            first = apply_mozyr_global_ice(session)
            if not first.created_city:
                session.execute(
                    text("DELETE FROM ice_parser_jobs WHERE arena_id = :aid"),
                    {"aid": first.arena_id},
                )
                session.execute(
                    text("DELETE FROM arena_profiles WHERE arena_id = :aid"),
                    {"aid": first.arena_id},
                )
                session.execute(text("DELETE FROM arenas WHERE id = :aid"), {"aid": first.arena_id})
                session.execute(
                    text("DELETE FROM cities WHERE id = :cid AND name = :name"),
                    {"cid": first.city_id, "name": CITY_NAME},
                )
                first = apply_mozyr_global_ice(session)
            second = apply_mozyr_global_ice(session)
            assert first.city_id == second.city_id
            assert first.arena_id == second.arena_id
            assert first.created_city
            assert first.created_arena
            assert first.created_profile
            assert first.created_job
            assert not second.created_city
            assert not second.created_arena
            assert not second.created_profile
            assert not second.created_job
            assert second.updated_job

            job = session.execute(
                text(
                    "SELECT parser_key FROM ice_parser_jobs WHERE arena_id = :aid"
                ),
                {"aid": first.arena_id},
            ).fetchone()
            assert job is not None
            assert job[0] == PARSER_KEY_WEEKLY_GRID_V1
        finally:
            trans.rollback()


def test_does_not_modify_existing_arena_id_44() -> None:
    engine = create_engine(_sync_url())
    with Session(engine) as session:
        trans = session.begin()
        try:
            cid = int(
                session.execute(
                    text(
                        """
                        INSERT INTO cities (name, sort_order, country, price_group)
                        VALUES (:name, 99, 'RU', 'RU_BASE')
                        RETURNING id
                        """
                    ),
                    {"name": f"Moscow-{uuid.uuid4().hex[:6]}"},
                ).scalar_one()
            )
            session.execute(
                text(
                    """
                    INSERT INTO arenas (id, city_id, name, address, is_active, is_confirmed)
                    VALUES (44, :cid, 'Ледовый дворец Центральный', 'Москва', true, true)
                    """
                ),
                {"cid": cid},
            )
            session.execute(
                text(
                    """
                    INSERT INTO arena_profiles (arena_id, city_id, slug, timezone, status, amenities, social_urls)
                    VALUES (44, :cid, 'moscow-central-blocker', 'Europe/Moscow', 'published', '{}'::jsonb, '{}'::jsonb)
                    """
                ),
                {"cid": cid},
            )
            result = apply_mozyr_global_ice(session)
            assert result.arena_id != 44
            moscow_name = session.execute(
                text("SELECT name FROM arenas WHERE id = 44"),
            ).scalar_one()
            assert "Центральный" in moscow_name
            mozyr_name = session.execute(
                text(
                    """
                    SELECT a.name FROM arenas a
                    JOIN arena_profiles p ON p.arena_id = a.id
                    JOIN cities c ON c.id = a.city_id
                    WHERE c.name = :city AND p.slug = :slug
                    """
                ),
                {"city": CITY_NAME, "slug": SLUG},
            ).scalar_one()
            assert mozyr_name == ARENA_NAME
        finally:
            trans.rollback()
