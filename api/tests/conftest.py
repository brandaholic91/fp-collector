import os
import pathlib

os.environ.setdefault("DATABASE_URL", "postgresql://fpcollector:changeme@localhost:15432/fpcollector_test")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100")

import pytest
import pytest_asyncio
import asyncpg
from httpx import AsyncClient, ASGITransport


INIT_SQL = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"


def pytest_configure(config):
    config.addinivalue_line("markers", "no_db: skip database fixtures")


@pytest_asyncio.fixture
async def db_pool():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(INIT_SQL.read_text())
    yield pool
    await pool.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_db(request):
    if request.node.get_closest_marker("no_db"):
        yield
        return
    # Need to manually create a pool for cleanup
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    yield
    async with pool.acquire() as conn:
        await conn.execute("TRUNCATE raw_events, clean_events, leads RESTART IDENTITY CASCADE")
    await pool.close()


@pytest_asyncio.fixture
async def client():
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
