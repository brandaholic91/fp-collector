import pytest


@pytest.mark.asyncio
async def test_raw_events_has_processing_state_columns(db_pool):
    async with db_pool.acquire() as conn:
        cols = await conn.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'raw_events'
              AND column_name IN ('processed_at', 'processing_error')
            ORDER BY column_name
        """)
    assert len(cols) == 2
    by_name = {c["column_name"]: c for c in cols}
    assert by_name["processed_at"]["data_type"] == "timestamp with time zone"
    assert by_name["processed_at"]["is_nullable"] == "YES"
    assert by_name["processing_error"]["data_type"] == "text"
    assert by_name["processing_error"]["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_raw_events_has_unprocessed_partial_index(db_pool):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'raw_events'
              AND indexname = 'idx_raw_events_unprocessed'
        """)
    assert len(rows) == 1
    indexdef = rows[0]["indexdef"].lower()
    assert "where" in indexdef
    assert "processed_at is null" in indexdef
    assert "processing_error is null" in indexdef
