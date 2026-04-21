import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio


N8N_WORKER_URL = os.environ.get(
    "N8N_WORKER_DATABASE_URL",
    "postgresql://n8n_worker:changeme_n8n_worker@db:5432/fpcollector_test",
)


@pytest_asyncio.fixture
async def worker_conn():
    conn = await asyncpg.connect(N8N_WORKER_URL)
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def seed_event(db_pool):
    eid = uuid.uuid4()
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO raw_events (
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, consent_analytics, payload
            ) VALUES ($1, 'page_view', $2, 'sess', 'anon', 'https://x/', true, '{}')
            RETURNING id
            """,
            eid, datetime.now(timezone.utc),
        )
    return {"id": row["id"], "event_id": eid}


@pytest.mark.asyncio
async def test_worker_can_select_raw_events(worker_conn, seed_event):
    rows = await worker_conn.fetch("SELECT id FROM raw_events WHERE id = $1", seed_event["id"])
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_worker_can_update_processed_at(worker_conn, seed_event):
    await worker_conn.execute(
        "UPDATE raw_events SET processed_at = now() WHERE id = $1", seed_event["id"]
    )


@pytest.mark.asyncio
async def test_worker_can_update_processing_error(worker_conn, seed_event):
    await worker_conn.execute(
        "UPDATE raw_events SET processing_error = 'test' WHERE id = $1", seed_event["id"]
    )


@pytest.mark.asyncio
async def test_worker_cannot_update_other_columns(worker_conn, seed_event):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await worker_conn.execute(
            "UPDATE raw_events SET event_name = 'hacked' WHERE id = $1", seed_event["id"]
        )


@pytest.mark.asyncio
async def test_worker_cannot_delete_from_raw_events(worker_conn, seed_event):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await worker_conn.execute("DELETE FROM raw_events WHERE id = $1", seed_event["id"])


@pytest.mark.asyncio
async def test_worker_can_insert_clean_events(worker_conn, seed_event):
    await worker_conn.execute(
        """
        INSERT INTO clean_events (
            raw_event_id, event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, source_medium
        ) VALUES ($1, $2, 'page_view', now(), 'sess', 'anon', 'https://x/', 'direct / none')
        """,
        seed_event["id"], seed_event["event_id"],
    )


@pytest.mark.asyncio
async def test_worker_cannot_delete_from_clean_events(worker_conn):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await worker_conn.execute("DELETE FROM clean_events")


@pytest.mark.asyncio
async def test_worker_can_insert_leads(worker_conn, seed_event):
    await worker_conn.execute(
        """
        INSERT INTO clean_events (
            raw_event_id, event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, source_medium
        ) VALUES ($1, $2, 'form_submit', now(), 'sess', 'anon', 'https://x/', 'direct / none')
        """,
        seed_event["id"], seed_event["event_id"],
    )
    await worker_conn.execute(
        """
        INSERT INTO leads (event_id, anonymous_id, occurred_at, payload)
        VALUES ($1, 'anon', now(), '{"email": "test@example.com"}')
        """,
        seed_event["event_id"],
    )
