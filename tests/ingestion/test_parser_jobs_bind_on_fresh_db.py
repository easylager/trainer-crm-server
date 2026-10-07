"""Fresh database: real arena seeds bind every parser job by (city, slug).

Empty database → alembic head → capital + regional arena seeds → both job builders
→ upsert. A four-arena fixture hides slug mismatches in the Minsk / SPb / Moscow specs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from src.ingestion.arena_seed import SeedArena, arenas_by_parser_key
from src.ingestion.capital_arenas import ARENAS as CAPITAL_ARENAS
from src.ingestion.capital_arenas import apply_capital_arenas
from src.ingestion.regional_arenas import ARENAS as REGIONAL_ARENAS
from src.ingestion.regional_arenas import apply_regional_arenas
from src.ingestion.seed_jobs import build_minsk_job_seeds, upsert_ice_parser_jobs
from src.shared.config import Settings

ROOT = Path(__file__).resolve().parents[2]
BIND_DB = "trainer_crm_test_task196_bind"


def _sync_url_from_settings() -> str:
    raw = os.environ.get("DATABASE_URL_SYNC") or os.environ.get("DATABASE_URL")
    if not raw:
        settings = Settings()
        raw = settings.database_url_sync or settings.database_url
    if raw.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + raw[len("postgresql+asyncpg://") :]
    if raw.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw[len("postgresql://") :]
    return raw


def _async_url(sync_url: str) -> str:
    if sync_url.startswith("postgresql+psycopg://"):
        return "postgresql+asyncpg://" + sync_url[len("postgresql+psycopg://") :]
    if sync_url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + sync_url[len("postgresql://") :]
    raise RuntimeError(f"unsupported database url scheme: {sync_url!r}")


def _with_database(url: str, name: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{name}"))


def _admin_psycopg_url(sync_url: str) -> str:
    admin = _with_database(sync_url, "postgres")
    if admin.startswith("postgresql+psycopg://"):
        return "postgresql://" + admin[len("postgresql+psycopg://") :]
    return admin


def _recreate_database(admin_url: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (BIND_DB,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{BIND_DB}"')
        conn.execute(f'CREATE DATABASE "{BIND_DB}"')


def _drop_database(admin_url: str) -> None:
    import psycopg

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid()
            """,
            (BIND_DB,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{BIND_DB}"')


def _expected() -> dict[str, tuple[str, str]]:
    expected: dict[str, tuple[str, str]] = {}
    for arena in (*CAPITAL_ARENAS, *REGIONAL_ARENAS):
        if not arena.parser_key:
            continue
        if arena.parser_key in expected:
            raise AssertionError(f"duplicate parser_key {arena.parser_key}")
        expected[arena.parser_key] = (arena.city_name, arena.slug)
    return expected


def _assert_specs_match_capital_seed() -> None:
    """Minsk / Moscow / SPb specs must carry the same (city, slug) as the capital seed."""
    by_key = arenas_by_parser_key(CAPITAL_ARENAS)
    seeds = build_minsk_job_seeds()
    got = {seed.parser_key: (seed.config.get("city_name"), seed.config.get("arena_slug")) for seed in seeds}
    assert got.keys() == by_key.keys()
    for parser_key, arena in by_key.items():
        assert got[parser_key] == (arena.city_name, arena.slug), parser_key
        assert len(arena.name) <= 128


def _seed(sync_url: str) -> None:
    engine = create_engine(sync_url)
    try:
        with Session(engine) as session:
            apply_capital_arenas(session, verbose=False)
            apply_regional_arenas(session, verbose=False)
            session.commit()
    finally:
        engine.dispose()


async def _bind(async_url: str, expected: dict[str, tuple[str, str]]) -> None:
    from scripts.seed_regional_ice_parser_jobs import build_regional_job_seeds

    minsk = build_minsk_job_seeds()
    regional = build_regional_job_seeds()
    seeds = [*minsk, *regional]
    assert {seed.parser_key for seed in seeds} == set(expected)
    assert len(seeds) == 42
    for seed in seeds:
        city_name, slug = expected[seed.parser_key]
        assert seed.config["city_name"] == city_name
        assert seed.config["arena_slug"] == slug

    engine = create_async_engine(async_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            report = await upsert_ice_parser_jobs(session, seeds)
            await session.commit()
            assert report.inserted == len(seeds)
            assert report.updated == 0
            assert report.skipped_missing_arena == 0
            rows = (await session.execute(text("""
                        SELECT ipj.parser_key, c.name, ap.slug
                        FROM ice_parser_jobs ipj
                        JOIN arenas a ON a.id = ipj.arena_id
                        JOIN arena_profiles ap ON ap.arena_id = a.id
                        JOIN cities c ON c.id = a.city_id
                        ORDER BY ipj.parser_key
                        """))).fetchall()
        bound = {parser_key: (city_name, slug) for parser_key, city_name, slug in rows}
        assert bound == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_database_binds_every_parser_job() -> None:
    """AC: empty DB, migrations, real seeds, both job builders, one binding per parser_key."""
    if BIND_DB in {"trainer_crm", "trainer_crm_test"}:
        raise RuntimeError(BIND_DB)
    _assert_specs_match_capital_seed()
    expected = _expected()
    assert len(expected) == 42
    assert len(arenas_by_parser_key(CAPITAL_ARENAS)) == 24
    assert len(arenas_by_parser_key(REGIONAL_ARENAS)) == 18

    base_sync = _sync_url_from_settings()
    parsed = urlparse(base_sync)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"} and not host.startswith("127."):
        pytest.skip(f"refusing to create a database on host {host!r}")

    sync_url = _with_database(base_sync, BIND_DB)
    async_url = _async_url(sync_url)
    admin_url = _admin_psycopg_url(base_sync)
    if urlparse(sync_url).path.strip("/") != BIND_DB:
        raise RuntimeError(f"refusing to migrate {sync_url}")

    _recreate_database(admin_url)
    try:
        env = os.environ.copy()
        env["DATABASE_URL"] = async_url
        env["DATABASE_URL_SYNC"] = sync_url
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        _seed(sync_url)
        await _bind(async_url, expected)
    finally:
        _drop_database(admin_url)


def test_seed_arena_ids_do_not_overlap() -> None:
    capital_ids = {arena.arena_id for arena in CAPITAL_ARENAS}
    regional_ids = {arena.arena_id for arena in REGIONAL_ARENAS}
    assert not capital_ids & regional_ids
    assert all(isinstance(arena, SeedArena) for arena in (*CAPITAL_ARENAS, *REGIONAL_ARENAS))
