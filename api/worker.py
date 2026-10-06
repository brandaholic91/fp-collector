import asyncio
import logging
import signal

import asyncpg

from config import settings
from pipeline import process_event, process_rows_batched

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 100
BATCHED_SIZE = 5000
_shutdown = False


def _handle_sigterm(*_):
    global _shutdown
    log.info("SIGTERM received, shutting down after current batch")
    _shutdown = True


async def process_batch(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_id, event_name, occurred_at, session_id, anonymous_id,
                   page_url, referrer, utm_source, utm_medium, utm_campaign,
                   utm_term, utm_content, fbclid, payload
            FROM raw_events
            WHERE processed_at IS NULL AND processing_error IS NULL
            ORDER BY id
            LIMIT $1
            FOR UPDATE SKIP LOCKED
            """,
            BATCHED_SIZE if settings.worker_batched else BATCH_SIZE,
        )

        if settings.worker_batched and rows:
            try:
                await process_rows_batched(conn, rows)
                log.info("Processed %d events (batched)", len(rows))
                return len(rows)
            except Exception as exc:
                log.error("Batched processing failed, falling back to per-event: %s", exc)

        processed = 0
        for row in rows:
            try:
                await process_event(conn, row)
                processed += 1
            except Exception as exc:
                log.error("Failed to process event %s: %s", row["event_id"], exc)
                await conn.execute(
                    "UPDATE raw_events SET processing_error = $1 WHERE id = $2",
                    str(exc), row["id"],
                )

    if processed:
        log.info("Processed %d events", processed)
    return processed


async def run():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    pool = await asyncpg.create_pool(settings.database_url)
    log.info("Worker started, poll interval %ds", settings.worker_poll_interval)

    try:
        while not _shutdown:
            count = await process_batch(pool)
            if count == 0:
                await asyncio.sleep(settings.worker_poll_interval)
    finally:
        await pool.close()
        log.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(run())
