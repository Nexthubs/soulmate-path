import os
import sys
from typing import AsyncGenerator
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from app.core.config import settings


def get_sync_database_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def get_async_database_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


# Synchronous engine & session maker (used by Alembic & sync test harnesses)
sync_engine = create_engine(
    get_sync_database_url(),
    echo=settings.debug,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Detect test runner to avoid asyncpg cross-event-loop pooled connection reuse
is_test_runner = (
    "pytest" in sys.modules
    or bool(os.environ.get("PYTEST_CURRENT_TEST"))
    or settings.environment in ("test", "testing")
)

# Asynchronous engine & session maker (used by FastAPI async endpoints)
async_engine = create_async_engine(
    get_async_database_url(),
    echo=settings.debug,
    poolclass=NullPool if is_test_runner else None,
    pool_pre_ping=not is_test_runner,
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
