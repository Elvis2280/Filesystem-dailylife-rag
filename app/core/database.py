from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)

async_engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)

SYNC_DATABASE_URL = (
    f"postgresql+psycopg2://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
)
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)
sync_session = sessionmaker(sync_engine, expire_on_commit=False)

Base = declarative_base()


async def get_db() -> AsyncSession:
    """Provide an async database session for FastAPI dependency injection.

    Yields:
        AsyncSession: An async SQLAlchemy session.
    """
    async with async_session() as session:
        yield session


@contextmanager
def get_sync_db():
    """Provide a sync database session for Celery workers.

    Yields:
        Session: A sync SQLAlchemy session. Automatically closed on exit.
    """
    db = sync_session()
    try:
        yield db
    finally:
        db.close()
