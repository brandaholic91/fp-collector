import os
os.environ.setdefault("DATABASE_URL", "postgresql://fpcollector:changeme@localhost:5432/fpcollector_test")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100")

import pytest
import pytest_asyncio
import asyncpg
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture(scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(open("db/init.sql").read())
    yield pool
    await pool.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_db(db_pool):
    yield
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE raw_events, clean_events, leads RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture
async def client():
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
