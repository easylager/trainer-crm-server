"""
Async DB session for runtime. Migrations use sync URL; app uses async.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config import Settings

from .models import Base

_settings = Settings()
# Async URL for app (asyncpg)
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
