"""
Pytest fixtures for integration and API tests.
Uses DATABASE_URL from env (or .env) — for tests point it to trainer_crm_test and run: alembic upgrade head

Engine and session are created per test (function scope) in the same event loop that runs the test,
so asyncpg never sees "another operation in progress" or "Future attached to a different loop".
"""
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config import Settings


def belarus_test_phone(telegram_id: int) -> tuple[str, str]:
    """
    Stable unique Belarus-shaped phone per telegram_id for tests.
    Avoids ix_clients_telegram_id / ix_clients_phone_normalized collisions when the DB is reused across tests.
    """
    nine = telegram_id % (10**9)
    normalized = f"375{nine:09d}"
    return f"+{normalized}", normalized


def unique_test_telegram_id() -> int:
    """
    Random Telegram-like id in a high range so integration/e2e tests do not collide
    with each other or with rows left from previous runs on a dev database.
    """
    return 6_000_000_000 + (uuid.uuid4().int % 999_999_999)


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
