# Pipeline Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the n8n pipeline with a self-hosted Python worker that polls `raw_events` and processes them into `clean_events` and `leads`.

**Architecture:** A `pipeline.py` module holds pure pipeline logic (source_medium computation, per-event processing); `worker.py` holds the poll loop and DB pool lifecycle. Both run from the same Docker image as the API, as a separate container with `command: python worker.py`.

**Tech Stack:** Python 3.11, asyncpg, asyncio, pydantic-settings, pytest-asyncio

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `api/pipeline.py` | Pure pipeline logic: `compute_source_medium`, `process_event` |
| Create | `api/worker.py` | Poll loop, DB pool lifecycle, graceful shutdown |
| Create | `api/tests/test_pipeline.py` | Unit + integration tests for pipeline logic |
| Modify | `api/config.py` | Add `worker_poll_interval` setting |
| Modify | `docker-compose.yml` | Add `worker` service |
| Modify | `.env.example` | Document `WORKER_POLL_INTERVAL` |

---

## Task 1: Add WORKER_POLL_INTERVAL to config

**Files:**
- Modify: `api/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add setting to config.py**

Replace the contents of `api/config.py` with:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    rate_limit_per_minute: int = 100
    allowed_origins: str = "*"
    worker_poll_interval: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Document in .env.example**

Add after the `ALLOWED_ORIGINS` line in `.env.example`:

```
WORKER_POLL_INTERVAL=10
```

- [ ] **Step 3: Commit**

```bash
git add api/config.py .env.example
git commit -m "feat: add WORKER_POLL_INTERVAL config setting"
```

---

## Task 2: Implement compute_source_medium with tests (TDD)

**Files:**
- Create: `api/pipeline.py`
- Create: `api/tests/test_pipeline.py`

- [ ] **Step 1: Write failing tests**

Create `api/tests/test_pipeline.py`:

```python
import pytest
from pipeline import compute_source_medium


def test_utm_params_take_priority():
    source, medium = compute_source_medium("Google", "CPC", None, "https://facebook.com/")
    assert source == "google"
    assert medium == "cpc"


def test_fbclid_fallback():
    source, medium = compute_source_medium(None, None, "abc123", None)
    assert source == "facebook"
    assert medium == "cpc"


def test_google_referrer():
    source, medium = compute_source_medium(None, None, None, "https://www.google.com/search?q=test")
    assert source == "google"
    assert medium == "organic"


def test_facebook_referrer():
    source, medium = compute_source_medium(None, None, None, "https://www.facebook.com/")
    assert source == "facebook"
    assert medium == "referral"


def test_instagram_referrer():
    source, medium = compute_source_medium(None, None, None, "https://instagram.com/p/abc")
    assert source == "facebook"
    assert medium == "referral"


def test_linkedin_referrer():
    source, medium = compute_source_medium(None, None, None, "https://linkedin.com/in/user")
    assert source == "linkedin"
    assert medium == "referral"


def test_twitter_referrer():
    source, medium = compute_source_medium(None, None, None, "https://twitter.com/user")
    assert source == "twitter"
    assert medium == "referral"


def test_x_com_referrer():
    source, medium = compute_source_medium(None, None, None, "https://x.com/user")
    assert source == "twitter"
    assert medium == "referral"


def test_unknown_referrer():
    source, medium = compute_source_medium(None, None, None, "https://somesite.com/page")
    assert source == "somesite.com"
    assert medium == "referral"


def test_no_referrer_is_direct():
    source, medium = compute_source_medium(None, None, None, None)
    assert source == "direct"
    assert medium == "none"


def test_empty_referrer_is_direct():
    source, medium = compute_source_medium(None, None, None, "")
    assert source == "direct"
    assert medium == "none"


def test_utm_requires_both_source_and_medium():
    # utm_source alone without utm_medium falls through to referrer logic
    source, medium = compute_source_medium("google", None, None, "https://facebook.com/")
    assert source == "facebook"
    assert medium == "referral"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_pipeline.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'pipeline'`

- [ ] **Step 3: Create api/pipeline.py with compute_source_medium**

```python
import re
import asyncpg


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"^https?://([^/:?#]+)", url, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower().removeprefix("www.")


def compute_source_medium(
    utm_source: str | None,
    utm_medium: str | None,
    fbclid: str | None,
    referrer: str | None,
) -> tuple[str, str]:
    if utm_source and utm_medium:
        return utm_source.lower(), utm_medium.lower()
    if fbclid:
        return "facebook", "cpc"
    host = _hostname(referrer)
    if host:
        if "google." in host:
            return "google", "organic"
        if "facebook." in host or "instagram." in host:
            return "facebook", "referral"
        if "linkedin." in host:
            return "linkedin", "referral"
        if "twitter." in host or "t.co" == host or "x.com" == host:
            return "twitter", "referral"
        return host, "referral"
    return "direct", "none"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_pipeline.py -v
```

Expected: all 13 tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/pipeline.py api/tests/test_pipeline.py
git commit -m "feat: add compute_source_medium with tests"
```

---

## Task 3: Implement process_event with integration tests (TDD)

**Files:**
- Modify: `api/pipeline.py`
- Modify: `api/tests/test_pipeline.py`

- [ ] **Step 1: Add failing integration tests**

Append to `api/tests/test_pipeline.py`:

```python
import uuid
import json
from datetime import datetime, timezone
import pytest_asyncio
from pipeline import process_event


def _raw_event(**kwargs):
    defaults = {
        "id": 1,
        "event_id": uuid.uuid4(),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc),
        "session_id": "sess-test",
        "anonymous_id": "anon-test",
        "page_url": "https://example.com/",
        "referrer": None,
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "test_campaign",
        "utm_term": None,
        "utm_content": None,
        "fbclid": None,
        "payload": "{}",
    }
    defaults.update(kwargs)
    return defaults


@pytest.mark.asyncio
async def test_process_event_inserts_clean_event(db_pool):
    row = _raw_event()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, utm_campaign, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,true,$10::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["utm_campaign"], row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        clean = await conn.fetchrow("SELECT * FROM clean_events WHERE event_id=$1", row["event_id"])
        assert clean is not None
        assert clean["event_name"] == "page_view"
        assert clean["source_medium"] == "google / cpc"
        assert clean["utm_source"] == "google"

        raw = await conn.fetchrow("SELECT processed_at, processing_error FROM raw_events WHERE event_id=$1", row["event_id"])
        assert raw["processed_at"] is not None
        assert raw["processing_error"] is None


@pytest.mark.asyncio
async def test_process_event_creates_lead_for_form_submit(db_pool):
    row = _raw_event(event_name="form_submit", payload='{"email": "test@example.com"}')
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        lead = await conn.fetchrow("SELECT * FROM leads WHERE event_id=$1", row["event_id"])
        assert lead is not None
        assert lead["utm_source"] == "google"


@pytest.mark.asyncio
async def test_process_event_no_lead_for_page_view(db_pool):
    row = _raw_event(event_name="page_view")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        lead = await conn.fetchrow("SELECT * FROM leads WHERE event_id=$1", row["event_id"])
        assert lead is None


@pytest.mark.asyncio
async def test_process_event_duplicate_is_idempotent(db_pool):
    row = _raw_event()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)
        # second call should not raise
        await process_event(conn, db_row)

        count = await conn.fetchval("SELECT COUNT(*) FROM clean_events WHERE event_id=$1", row["event_id"])
        assert count == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_pipeline.py::test_process_event_inserts_clean_event -v
```

Expected: `ImportError: cannot import name 'process_event' from 'pipeline'`

- [ ] **Step 3: Add process_event to api/pipeline.py**

Append to `api/pipeline.py`:

```python
async def process_event(conn: asyncpg.Connection, row: asyncpg.Record) -> None:
    source, medium = compute_source_medium(
        row["utm_source"], row["utm_medium"], row["fbclid"], row["referrer"]
    )
    source_medium = f"{source} / {medium}"

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO clean_events (
                raw_event_id, event_id, event_name, occurred_at, session_id,
                anonymous_id, page_url, referrer, utm_source, utm_medium,
                utm_campaign, source_medium, payload
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (event_id) DO NOTHING
            """,
            row["id"], row["event_id"], row["event_name"], row["occurred_at"],
            row["session_id"], row["anonymous_id"], row["page_url"], row["referrer"],
            row["utm_source"] or None, row["utm_medium"] or None,
            row["utm_campaign"] or None, source_medium, row["payload"],
        )

        if row["event_name"] == "form_submit":
            await conn.execute(
                """
                INSERT INTO leads (
                    event_id, anonymous_id, occurred_at,
                    utm_source, utm_medium, utm_campaign, payload
                )
                SELECT $1,$2,$3,$4,$5,$6,$7
                WHERE NOT EXISTS (SELECT 1 FROM leads WHERE event_id = $1)
                """,
                row["event_id"], row["anonymous_id"], row["occurred_at"],
                row["utm_source"] or None, row["utm_medium"] or None,
                row["utm_campaign"] or None, row["payload"],
            )

        await conn.execute(
            "UPDATE raw_events SET processed_at = now() WHERE id = $1",
            row["id"],
        )
```

- [ ] **Step 4: Run integration tests**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_pipeline.py -v
```

Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/pipeline.py api/tests/test_pipeline.py
git commit -m "feat: add process_event with integration tests"
```

---

## Task 4: Write worker.py poll loop

**Files:**
- Create: `api/worker.py`

- [ ] **Step 1: Create api/worker.py**

```python
import asyncio
import logging
import signal

import asyncpg

from config import settings
from pipeline import process_event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 100
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
            """,
            BATCH_SIZE,
        )

    processed = 0
    for row in rows:
        async with pool.acquire() as conn:
            try:
                await process_event(conn, row)
                processed += 1
            except Exception as exc:
                log.error("Failed to process event %s: %s", row["event_id"], exc)
                async with pool.acquire() as err_conn:
                    await err_conn.execute(
                        "UPDATE raw_events SET processing_error = $1 WHERE id = $2",
                        str(exc), row["id"],
                    )

    if processed:
        log.info("Processed %d events", processed)
    return processed


async def run():
    signal.signal(signal.SIGTERM, _handle_sigterm)
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
```

- [ ] **Step 2: Verify script runs without import errors**

```bash
cd /home/brandaholic/Playground/fp-collector/api
python -c "import worker; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add api/worker.py
git commit -m "feat: add pipeline worker poll loop"
```

---

## Task 5: Add worker service to docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add worker service**

In `docker-compose.yml`, add after the `api` service block:

```yaml
  worker:
    build: ./api
    image: fp-collector-api:1.0.0
    command: python worker.py
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    networks:
      - internal
```

- [ ] **Step 2: Validate compose syntax**

```bash
docker compose config --quiet && echo "ok"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add worker service to docker-compose"
```

---

## Task 6: Update smoke test to test worker directly

**Files:**
- Modify: `api/tests/test_phase2_smoke.py`

The existing smoke test waits for n8n to process events. Replace the pipeline wait with a direct call to `process_batch` so the smoke test works without n8n.

- [ ] **Step 1: Replace test_phase2_smoke.py**

```python
import uuid
from datetime import datetime, timezone

import pytest
import asyncpg

from pipeline import process_event


async def _seed_events(pool, events):
    async with pool.acquire() as conn:
        for e in events:
            await conn.execute(
                """
                INSERT INTO raw_events (
                    event_id, event_name, occurred_at, session_id, anonymous_id,
                    page_url, referrer, utm_source, utm_medium, utm_campaign,
                    fbclid, consent_analytics, payload
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, true, $12::jsonb)
                """,
                e["event_id"], e["event_name"], e["occurred_at"], e["session_id"],
                e["anonymous_id"], e["page_url"], e.get("referrer"),
                e.get("utm_source"), e.get("utm_medium"), e.get("utm_campaign"),
                e.get("fbclid"), e.get("payload", "{}"),
            )


@pytest.mark.asyncio
async def test_end_to_end_pipeline(db_pool):
    now = datetime.now(timezone.utc)
    events = [
        {
            "event_id": uuid.uuid4(),
            "event_name": "page_view",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring_sale",
        },
        {
            "event_id": uuid.uuid4(),
            "event_name": "cta_click",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/",
            "referrer": "https://www.facebook.com/",
        },
        {
            "event_id": uuid.uuid4(),
            "event_name": "form_submit",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/thanks",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring_sale",
            "payload": '{"email": "smoke@example.com"}',
        },
    ]
    await _seed_events(db_pool, events)

    event_ids = [e["event_id"] for e in events]
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM raw_events WHERE event_id = ANY($1)", event_ids
        )
        for row in rows:
            await process_event(conn, row)

    async with db_pool.acquire() as conn:
        raw_rows = await conn.fetch(
            "SELECT event_id, processed_at, processing_error FROM raw_events WHERE event_id = ANY($1)",
            event_ids,
        )
        assert len(raw_rows) == 3
        for r in raw_rows:
            assert r["processed_at"] is not None, f"not processed: {r['event_id']}"
            assert r["processing_error"] is None, f"has error: {r['processing_error']}"

        clean = {
            r["event_id"]: r
            for r in await conn.fetch(
                "SELECT event_id, source_medium FROM clean_events WHERE event_id = ANY($1)",
                event_ids,
            )
        }
        assert len(clean) == 3
        assert clean[events[0]["event_id"]]["source_medium"] == "google / cpc"
        assert clean[events[1]["event_id"]]["source_medium"] == "facebook / referral"
        assert clean[events[2]["event_id"]]["source_medium"] == "google / cpc"

        leads = await conn.fetch(
            "SELECT event_id, payload FROM leads WHERE event_id = ANY($1)", event_ids
        )
        assert len(leads) == 1
        assert leads[0]["event_id"] == events[2]["event_id"]
        payload = leads[0]["payload"]
        if isinstance(payload, str):
            import json
            payload = json.loads(payload)
        assert payload["email"] == "smoke@example.com"
```

- [ ] **Step 2: Run full test suite**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 3: Commit and push**

```bash
git add api/tests/test_phase2_smoke.py
git commit -m "test: update smoke test to use pipeline worker directly"
git push
```
