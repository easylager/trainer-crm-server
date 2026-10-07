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


# Prod public identity. Literals on purpose: deriving this from ARENAS would not catch a wrong slug.
# (parser_key, city, slug, arena_id)
_PROD_BINDINGS: tuple[tuple[str, str, str, int], ...] = (
    ("balticarena_html_v1", "Санкт-Петербург/ЛО", "baltik-arena", 192),
    ("baranovichi_lds_v1", "Барановичи", "baranovichi-lds", 23),
    ("bobruisk_arena_v1", "Бобруйск", "bobruisk-arena", 38),
    ("brest_lds_v1", "Брест", "brest-lds", 22),
    ("bugryarena_html_v1", "Санкт-Петербург/ЛО", "ledovaya-arena-bugry", 111),
    ("chizhovka_html_v1", "Минск", "chizhovka", 6),
    ("diamond_html_v1", "Минск", "minsk-diamond", 7),
    ("dinamoyunior_html_v1", "Санкт-Петербург/ЛО", "ledovaya-arena-dinamo-yunior", 173),
    ("gomel_lds_v1", "Гомель", "gomel-lds", 33),
    ("gorki_lds_v1", "Горки", "gorki-lds", 32),
    ("grandice_json_v1", "Санкт-Петербург/ЛО", "ld-grand-kanon-ays", 99),
    ("grodno_neman_v1", "Гродно", "grodno-neman", 11),
    ("grodno_triniti_v1", "Гродно", "grodno-triniti", 10),
    ("iceburgarena_yclients_v1", "Санкт-Петербург/ЛО", "aysburg-arena", 193),
    ("izhorets_html_v1", "Санкт-Петербург/ЛО", "izhorets", 185),
    ("junost_instagram_caption_v1", "Минск", "minsk-junost", 8),
    ("kobrin_lds_v1", "Кобрин", "kobrin-lds", 25),
    ("kupchinoarena_html_v1", "Санкт-Петербург/ЛО", "ledovaya-arena-kupchino", 110),
    ("ldsokolniki_html_v1", "Москва/МО", "ledovyy-dvorets-sokolniki", 58),
    ("ledby_html_v1", "Минск", "ledby", 5),
    ("ledlife_origin_html_v1", "Минск", "minsk-ledlife", 4),
    ("ledovyydvorets_html_v1", "Санкт-Петербург/ЛО", "ledovyy-dvorets", 105),
    ("lida_lds_v1", "Лида", "lida-lds", 37),
    ("magnitarena_html_v1", "Санкт-Петербург/ЛО", "ledovaya-arena-magnit", 187),
    ("minskarena_main_saleframe_v1", "Минск", "minskarena", 2),
    ("minskarena_speed_oval_v1", "Минск", "konkobezhnaya-arena", 115),
    ("mogilev_ds_v1", "Могилев", "mogilev-ds", 43),
    ("molodechno_src_v1", "Молодечно", "molodechno-src", 18),
    ("novopolotsk_lds_v1", "Новополоцк", "novopolotsk-lds", 30),
    ("orsha_arena_v1", "Орша", "orsha-arena", 31),
    ("ostrovets_lds_v1", "Островец", "ostrovets-lds", 41),
    ("ozerki_gcal_v1", "Санкт-Петербург/ЛО", "ledovaya-arena-ozerki", 101),
    ("parnasarena_text_v1", "Санкт-Петербург/ЛО", "tsentr-ledovykh-vidov-sporta-parnas", 174),
    ("pinsk_volna_v1", "Пинск", "pinsk-volna", 24),
    ("shansarena_html_v1", "Санкт-Петербург/ЛО", "ledovyy-kompleks-shans-arena", 100),
    ("shklov_arena_v1", "Шклов", "shklov-arena", 42),
    ("shuvalovskyled_html_v1", "Санкт-Петербург/ЛО", "shuvalovskiy-led", 196),
    ("soligorsk_szk_v1", "Солигорск", "soligorsk-szk", 19),
    ("vitebsk_ds_v1", "Витебск", "vitebsk-ds", 29),
    ("vtbarena_qtickets_v1", "Москва/МО", "vtb-arena", 53),
    ("yubileyny_afisha_html_v1", "Санкт-Петербург/ЛО", "skk-yubileynyy", 97),
    ("zamok_html_v1", "Минск", "zamok", 3),
)


def _expected() -> dict[str, tuple[str, str, int]]:
    expected: dict[str, tuple[str, str, int]] = {}
    for parser_key, city_name, slug, arena_id in _PROD_BINDINGS:
        if parser_key in expected:
            raise AssertionError(f"duplicate parser_key {parser_key}")
        expected[parser_key] = (city_name, slug, arena_id)
    return expected


def _assert_seed_lists_match_prod_table(expected: dict[str, tuple[str, str, int]]) -> None:
    """Seed lists and Minsk/Moscow/SPb specs must match the literal prod table, not each other."""
    seeded: dict[str, tuple[str, str, int]] = {}
    for arena in (*CAPITAL_ARENAS, *REGIONAL_ARENAS):
        if not arena.parser_key:
            continue
        seeded[arena.parser_key] = (arena.city_name, arena.slug, arena.arena_id)
        assert len(arena.name) <= 128
    assert seeded == expected
    minsk = build_minsk_job_seeds()
    capital_keys = {key for key, *_rest in _PROD_BINDINGS if key in {a.parser_key for a in CAPITAL_ARENAS}}
    got = {seed.parser_key: (seed.config.get("city_name"), seed.config.get("arena_slug")) for seed in minsk}
    assert set(got) == capital_keys
    for parser_key in capital_keys:
        city_name, slug, _arena_id = expected[parser_key]
        assert got[parser_key] == (city_name, slug), parser_key


def _seed(sync_url: str) -> None:
    engine = create_engine(sync_url)
    try:
        with Session(engine) as session:
            apply_capital_arenas(session, verbose=False)
            apply_regional_arenas(session, verbose=False)
            session.commit()
    finally:
        engine.dispose()


async def _bind(async_url: str, expected: dict[str, tuple[str, str, int]]) -> None:
    from scripts.seed_regional_ice_parser_jobs import build_regional_job_seeds

    minsk = build_minsk_job_seeds()
    regional = build_regional_job_seeds()
    seeds = [*minsk, *regional]
    assert {seed.parser_key for seed in seeds} == set(expected)
    assert len(seeds) == 42
    for seed in seeds:
        city_name, slug, _arena_id = expected[seed.parser_key]
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
                        SELECT ipj.parser_key, c.name, ap.slug, a.id, ap.status
                        FROM ice_parser_jobs ipj
                        JOIN arenas a ON a.id = ipj.arena_id
                        JOIN arena_profiles ap ON ap.arena_id = a.id
                        JOIN cities c ON c.id = a.city_id
                        ORDER BY ipj.parser_key
                        """))).fetchall()
        bound = {
            parser_key: (city_name, slug, int(arena_id)) for parser_key, city_name, slug, arena_id, _status in rows
        }
        assert bound == expected
        izhorets = next(row for row in rows if row[0] == "izhorets_html_v1")
        assert izhorets[4] == "published"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_database_binds_every_parser_job() -> None:
    """AC: empty DB, migrations, real seeds, both job builders, one binding per parser_key."""
    if BIND_DB in {"trainer_crm", "trainer_crm_test"}:
        raise RuntimeError(BIND_DB)
    expected = _expected()
    _assert_seed_lists_match_prod_table(expected)
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
