"""FastAPI dependencies: DB session for routes."""
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.db import get_async_session


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield async DB session; commits/rollback handled in use cases."""
    async for session in get_async_session():
        yield session
