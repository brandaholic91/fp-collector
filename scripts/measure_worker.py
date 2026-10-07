"""Measure worker throughput on N synthetic page_view rows.

    cd api && DATABASE_URL=... PYTHONPATH=. .venv/bin/python ../scripts/measure_worker.py 100000

Run it against the TEST database only: it truncates the event tables before and
after. Set WORKER_BATCHED=true to measure the batched mode.
"""
import asyncio
import logging
import os
import sys
import time

import asyncpg

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
TRUNCATE = "TRUNCATE raw_events, clean_events, leads RESTART IDENTITY CASCADE"


async def main():
    from config import settings
    from worker import process_batch

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(TRUNCATE)
        await conn.execute(
            """
            INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
                anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
            SELECT gen_random_uuid(), 'page_view', now(), 's' || (g / 5), 'a' || (g / 20),
                   'https://bolt.example/', 'google', 'cpc', true, '{}'::jsonb
            FROM generate_series(1, $1) g
            """,
            N,
        )

    start = time.perf_counter()
    done = 0
    while True:
        n = await process_batch(pool)
        if n == 0:
            break
        done += n
    elapsed = time.perf_counter() - start

    async with pool.acquire() as conn:
        await conn.execute(TRUNCATE)
    await pool.close()
    mode = "batched" if getattr(settings, "worker_batched", False) else "per-event"
    print(f"{mode}: {done} events in {elapsed:.1f} s = {done / elapsed:,.0f} events/s")


logging.disable(logging.INFO)   # the worker logs every batch
asyncio.run(main())
