import asyncio
import shutil
from pathlib import Path
import app.core.constant
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import settings
from app.core.database import Base

# ── Isolated test filesystem ──────────────────────────
TEST_BRAIN = Path(__file__).parent.parent / "test-brain"
if TEST_BRAIN.exists():
    shutil.rmtree(TEST_BRAIN)
TEST_BRAIN.mkdir(parents=True)


app.core.constant.WORKSPACE_BASE_PATH = str(TEST_BRAIN)

TEST_DB = "test_memoryrag"
TEST_DATABASE_URL = (
    f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
    f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{TEST_DB}"
)


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session")
async def create_test_db():
    conn = await create_async_engine(
        f"postgresql+asyncpg://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
        f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/postgres"
    ).connect()
    await conn.exec_driver_sql(f"DROP DATABASE IF EXISTS {TEST_DB}")
    await conn.exec_driver_sql(f"CREATE DATABASE {TEST_DB}")
    await conn.close()


@pytest_asyncio.fixture(scope="session")
async def engine(create_test_db):
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest_asyncio.fixture
async def client():
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_brain():
    yield
    if TEST_BRAIN.exists():
        for item in TEST_BRAIN.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
