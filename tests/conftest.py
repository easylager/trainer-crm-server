"""
Pytest fixtures for integration and API tests.
Uses DATABASE_URL from env (or .env) — for tests point it to trainer_crm_test and run: alembic upgrade head

Engine and session are created per test (function scope) in the same event loop that runs the test,
so asyncpg never sees "another operation in progress" or "Future attached to a different loop".
"""
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config import Settings


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; engine created in test's event loop, disposed after test."""
    settings = Settings()
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def app_use_test_db() -> AsyncGenerator[None, None]:
    """
    Patch app and infra to use a session factory created in the test's event loop.
    Use this fixture in API tests so /health and routes using get_session see the same loop.
    """
    settings = Settings()
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
    )
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    session_module = __import__("src.infrastructure.db.session", fromlist=["async_session_factory"])
    app_module = __import__("src.api.app", fromlist=["async_session_factory"])
    old_session_factory = session_module.async_session_factory
    old_app_factory = app_module.async_session_factory
    session_module.async_session_factory = factory
    app_module.async_session_factory = factory
    try:
        yield
    finally:
        session_module.async_session_factory = old_session_factory
        app_module.async_session_factory = old_app_factory
        await engine.dispose()
