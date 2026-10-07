"""TASK-196 AC-3: БД с нуля + сиды → парсеры привязаны к правильным аренам через slug.

Integration test verifies that parser-to-arena binding survives database recreation:
1. Create fresh DB with minimal seed data (cities, arenas with profiles+slugs)
2. Run ice_parser_jobs seeds (using arena_slug instead of numeric arena_id)
3. Assert each parser job resolves to the correct arena by comparing slug
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.ingestion.seed_jobs import JobSeed, upsert_ice_parser_jobs


@pytest.fixture
async def clean_db_with_arenas(db_session: AsyncSession) -> None:
    """Populate test DB with minimal cities+arenas for slug-based lookup."""
    # Insert test cities
    await db_session.execute(
        text("""
            INSERT INTO cities (id, name, country, is_active) VALUES
            (100, 'Минск', 'BY', true),
            (101, 'Гродно', 'BY', true),
            (102, 'Санкт-Петербург', 'RU', true)
            ON CONFLICT (id) DO NOTHING
        """)
    )
    
    # Insert test arenas
    await db_session.execute(
        text("""
            INSERT INTO arenas (id, city_id, name, address, is_active, is_confirmed) VALUES
            (200, 100, 'Минск Арена', 'пр-т Победителей 111', true, true),
            (201, 100, 'ТЦ Замок', 'пр-т Победителей 65', true, true),
            (202, 101, 'ТЦ Тринити', 'проспект Янки Купалы 87', true, true),
            (203, 102, 'Балтик Арена', 'Василеостровский намыв', true, true)
            ON CONFLICT (id) DO NOTHING
        """)
    )
    
    # Insert arena_profiles with stable slugs
    await db_session.execute(
        text("""
            INSERT INTO arena_profiles (arena_id, city_id, slug, status) VALUES
            (200, 100, 'minskarena', 'published'),
            (201, 100, 'zamok', 'published'),
            (202, 101, 'tc-triniti', 'published'),
            (203, 102, 'baltic-arena', 'published')
            ON CONFLICT (arena_id) DO NOTHING
        """)
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_parser_seeds_resolve_via_slug_not_id(
    db_session: AsyncSession,
    clean_db_with_arenas: None,
) -> None:
    """AC-3: Parser jobs created with (city_name, arena_slug) bind to correct arena_id."""
    # Define seeds using slug-based lookup (arena_id=0 as placeholder)
    seeds = [
        JobSeed(
            arena_id=0,  # Placeholder, will be resolved
            parser_key="minskarena_test_v1",
            cadence="daily",
            is_enabled=True,
            config={
                "arena_slug": "minskarena",
                "city_name": "Минск",
                "url": "https://test.example.com",
            },
            notes="test seed via slug",
        ),
        JobSeed(
            arena_id=0,
            parser_key="zamok_test_v1",
            cadence="daily",
            is_enabled=True,
            config={
                "arena_slug": "zamok",
                "city_name": "Минск",
                "url": "https://test.example.com",
            },
            notes="test seed via slug",
        ),
        JobSeed(
            arena_id=0,
            parser_key="triniti_test_v1",
            cadence="daily",
            is_enabled=True,
            config={
                "arena_slug": "tc-triniti",
                "city_name": "Гродно",
                "url": "https://test.example.com",
            },
            notes="test seed via slug",
        ),
        JobSeed(
            arena_id=0,
            parser_key="baltic_test_v1",
            cadence="daily",
            is_enabled=True,
            config={
                "arena_slug": "baltic-arena",
                "city_name": "Санкт-Петербург",
                "url": "https://test.example.com",
            },
            notes="test seed via slug",
        ),
    ]
    
    # Upsert parser jobs using slug resolution
    report = await upsert_ice_parser_jobs(db_session, seeds)
    await db_session.commit()
    
    # Assert all seeds were inserted (none skipped)
    assert report.inserted == 4
    assert report.skipped_missing_arena == 0
    
    # Verify each job was bound to the correct arena via slug lookup
    result = await db_session.execute(
        text("""
            SELECT ipj.parser_key, ipj.arena_id, ap.slug, c.name as city_name
            FROM ice_parser_jobs ipj
            JOIN arenas a ON a.id = ipj.arena_id
            JOIN arena_profiles ap ON ap.arena_id = a.id
            JOIN cities c ON c.id = a.city_id
            WHERE ipj.parser_key LIKE '%_test_v1'
            ORDER BY ipj.parser_key
        """)
    )
    jobs = result.mappings().all()
    
    expected = [
        ("baltic_test_v1", 203, "baltic-arena", "Санкт-Петербург"),
        ("minskarena_test_v1", 200, "minskarena", "Минск"),
        ("triniti_test_v1", 202, "tc-triniti", "Гродно"),
        ("zamok_test_v1", 201, "zamok", "Минск"),
    ]
    
    for idx, (parser_key, arena_id, slug, city_name) in enumerate(expected):
        job = jobs[idx]
        assert job["parser_key"] == parser_key
        assert job["arena_id"] == arena_id
        assert job["slug"] == slug
        assert job["city_name"] == city_name


@pytest.mark.asyncio
async def test_parser_seed_raises_on_missing_arena(db_session: AsyncSession, clean_db_with_arenas: None) -> None:
    """TASK-196: Parser seed with non-existent arena_slug raises ValueError with list of missing pairs."""
    seeds = [
        JobSeed(
            arena_id=0,
            parser_key="nonexistent_test_v1",
            cadence="daily",
            is_enabled=True,
            config={
                "arena_slug": "does-not-exist",
                "city_name": "Минск",
                "url": "https://test.example.com",
            },
            notes="test seed with missing arena",
        ),
    ]
    
    with pytest.raises(ValueError, match="Failed to resolve 1 parser"):
        await upsert_ice_parser_jobs(db_session, seeds)
    
    # Verify no job was created
    result = await db_session.execute(
        text("SELECT COUNT(*) FROM ice_parser_jobs WHERE parser_key = 'nonexistent_test_v1'")
    )
    count = result.scalar()
    assert count == 0


@pytest.mark.asyncio
async def test_legacy_arena_id_still_works(db_session: AsyncSession, clean_db_with_arenas: None) -> None:
    """Backward compatibility: seeds with explicit arena_id (not slug) still work."""
    seeds = [
        JobSeed(
            arena_id=200,  # Explicit ID, no slug lookup
            parser_key="legacy_test_v1",
            cadence="daily",
            is_enabled=True,
            config={"url": "https://test.example.com"},
            notes="test seed with explicit arena_id",
        ),
    ]
    
    report = await upsert_ice_parser_jobs(db_session, seeds)
    await db_session.commit()
    
    assert report.inserted == 1
    assert report.skipped_missing_arena == 0
    
    result = await db_session.execute(
        text("SELECT arena_id FROM ice_parser_jobs WHERE parser_key = 'legacy_test_v1'")
    )
    arena_id = result.scalar()
    assert arena_id == 200
