"""
Async DB session for runtime. Migrations use sync URL; app uses async.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config import Settings

from .models import Base

_settings = Settings()
# Async URL: Railway gives postgresql://, we need postgresql+asyncpg
_db_url = _settings.database_url
if _db_url.startswith("postgresql://") and "+asyncpg" not in _db_url:
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
# Fail fast when Postgres is down (hardware outage) instead of hanging Mini Apps
# until the reverse-proxy timeout. pool_pre_ping drops stale connections after failover.
engine = create_async_engine(
    _db_url,
    echo=_settings.debug,
    pool_pre_ping=True,
    pool_timeout=8,
    connect_args={"timeout": 8},
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
