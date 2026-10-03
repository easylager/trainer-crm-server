"""
Async DB session for runtime. Migrations use sync URL; app uses async.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.shared.config import Settings
from src.shared.ops_db_guard import async_database_url

from .models import Base

_settings = Settings()
_db_url = async_database_url(_settings.database_url)
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
