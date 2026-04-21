# fp-collector Phase 2 — n8n Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the n8n workflow that polls `raw_events`, enriches each row with a derived `source_medium`, writes to `clean_events`, creates `leads` rows from `form_submit` events, and routes failures to a dead-letter pattern.

**Architecture:** A single n8n workflow on the existing `martech-lab` n8n, polling PostgreSQL on `dokploy-lab` every 30s in batches of 100. A restricted `n8n_worker` DB user performs minimum-privilege reads and writes. Processing state (`processed_at`, `processing_error`) lives on `raw_events` itself.

**Tech Stack:** PostgreSQL 16.3, n8n (existing martech-lab instance), pytest + asyncpg for DB integration tests

---

## File Map

| File | Responsibility |
|---|---|
| `db/init.sql` | **Modified:** include `processed_at`, `processing_error` and the partial index |
| `db/migrations/002_add_processing_state.sql` | **New:** ALTER to add columns + partial index for existing deployments |
| `db/migrations/003_create_n8n_worker_user.sql` | **New:** create restricted `n8n_worker` user with least-privilege grants |
| `.env.example` | **Modified:** add `N8N_WORKER_PASSWORD` placeholder |
| `docker-compose.yml` | **Modified:** expose `db` to the martech-lab n8n (shared network OR LAN IP binding) |
| `api/tests/test_phase2_schema.py` | **New:** pytest validating the migration results (columns, index) |
| `api/tests/test_phase2_permissions.py` | **New:** pytest validating `n8n_worker` grants (what it can/cannot do) |
| `api/tests/test_phase2_smoke.py` | **New:** end-to-end integration test: seed raw_events → wait → assert clean_events + leads + processed_at |
| `n8n/workflows/fp-collector-pipeline.json` | **New:** exported n8n workflow |
| `n8n/README.md` | **New:** workflow import guide + attribution rules documentation |

---

## Prerequisites

Before starting, the following must be true:

1. Phase 1 is merged to `main`. The `raw_events` / `clean_events` / `leads` tables exist.
2. Local Docker stack from Phase 1 starts cleanly: `docker-compose up -d`.
3. `fpcollector_test` test database exists:
   ```bash
   docker-compose up -d db
   docker-compose exec db psql -U fpcollector -c "CREATE DATABASE fpcollector_test;"
   ```

## How tests run

Phase 2 tests run **inside the `api` container** (which already has pytest, asyncpg, and httpx installed via `requirements.txt`). The `db` service is reachable from inside the Docker network at hostname `db`, which the test DATABASE_URL uses.

Standard test run command used throughout this plan:

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/<file> -v
```

No `cd api` needed — the container's working directory is `/app` (which is `api/` from the repo root).

---

## Task 1: Schema extension — processing state columns

**Files:**
- Modify: `api/tests/conftest.py` (fix init.sql path bug from Phase 1)
- Modify: `db/init.sql`
- Create: `db/migrations/002_add_processing_state.sql`
- Create: `api/tests/test_phase2_schema.py`

- [ ] **Step 1a: Fix Phase 1 conftest.py path bug**

The Phase 1 conftest.py uses `open("db/init.sql")` which only works if cwd is the repo root. Since we run tests from inside the `api` container (cwd = `/app`), this resolves to `/app/db/init.sql`, which doesn't exist. Use a path anchored to the test file location instead.

Replace the `db_pool` fixture in `api/tests/conftest.py` with:

```python
import pathlib

INIT_SQL = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"


@pytest_asyncio.fixture(scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute(INIT_SQL.read_text())
    yield pool
    await pool.close()
```

The `INIT_SQL` resolution: `__file__` is `.../api/tests/conftest.py` → `.parent` = `tests/` → `.parent` = `api/` → `.parent` = repo root → then `db/init.sql`.

- [ ] **Step 1b: Write the failing test**

Create `api/tests/test_phase2_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker-compose up -d
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase2_schema.py -v
```

Expected: both tests `FAIL` — columns and index do not exist yet.

- [ ] **Step 3: Create `db/migrations/002_add_processing_state.sql`**

```sql
ALTER TABLE raw_events
    ADD COLUMN IF NOT EXISTS processed_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_error TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed
    ON raw_events (id)
    WHERE processed_at IS NULL AND processing_error IS NULL;
```

- [ ] **Step 4: Update `db/init.sql`**

Replace the `raw_events` CREATE TABLE and its indexes with the extended version. Open `db/init.sql` and find the `raw_events` block. Replace the table DDL and indexes so they look like this (keep `clean_events` and `leads` exactly as they were):

```sql
CREATE TABLE IF NOT EXISTS raw_events (
    id                BIGSERIAL   PRIMARY KEY,
    event_id          UUID        NOT NULL UNIQUE,
    event_name        TEXT        NOT NULL,
    occurred_at       TIMESTAMPTZ NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id        TEXT        NOT NULL,
    anonymous_id      TEXT        NOT NULL,
    page_url          TEXT        NOT NULL,
    referrer          TEXT,
    utm_source        TEXT,
    utm_medium        TEXT,
    utm_campaign      TEXT,
    utm_term          TEXT,
    utm_content       TEXT,
    fbclid            TEXT,
    consent_analytics BOOLEAN     NOT NULL,
    payload           JSONB       NOT NULL DEFAULT '{}',
    processed_at      TIMESTAMPTZ,
    processing_error  TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_events_occurred_at ON raw_events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_event_name  ON raw_events (event_name);
CREATE INDEX IF NOT EXISTS idx_raw_events_session_id  ON raw_events (session_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed ON raw_events (id)
    WHERE processed_at IS NULL AND processing_error IS NULL;
```

- [ ] **Step 5: Apply the migration to both local databases**

The conftest.py reloads `db/init.sql` at session start (picking up the updated schema), but existing DBs need the migration applied explicitly:

```bash
docker-compose exec -T db psql -U fpcollector -d fpcollector_test < db/migrations/002_add_processing_state.sql
docker-compose exec -T db psql -U fpcollector -d fpcollector      < db/migrations/002_add_processing_state.sql
```

Both statements are idempotent (`IF NOT EXISTS`), so re-running is safe.

- [ ] **Step 6: Run test to verify it passes**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase2_schema.py -v
```

Expected: both tests `PASS`.

- [ ] **Step 7: Commit**

```bash
git add api/tests/conftest.py db/init.sql db/migrations/002_add_processing_state.sql api/tests/test_phase2_schema.py
git commit -m "feat: add processing state columns and partial index to raw_events"
```

---

## Task 2: n8n_worker user migration

**Files:**
- Create: `db/migrations/003_create_n8n_worker_user.sql`
- Modify: `.env.example`

- [ ] **Step 1: Create `db/migrations/003_create_n8n_worker_user.sql`**

```sql
-- Run with: psql -v n8n_worker_password='YOUR_PASSWORD' -f 003_create_n8n_worker_user.sql

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_worker') THEN
    EXECUTE format('CREATE USER n8n_worker WITH PASSWORD %L', :'n8n_worker_password');
  ELSE
    EXECUTE format('ALTER USER n8n_worker WITH PASSWORD %L', :'n8n_worker_password');
  END IF;
END
$$;

GRANT CONNECT ON DATABASE fpcollector TO n8n_worker;
GRANT USAGE ON SCHEMA public TO n8n_worker;

GRANT SELECT ON raw_events TO n8n_worker;
GRANT UPDATE (processed_at, processing_error) ON raw_events TO n8n_worker;

GRANT INSERT ON clean_events TO n8n_worker;
GRANT INSERT ON leads TO n8n_worker;

GRANT USAGE, SELECT ON SEQUENCE clean_events_id_seq TO n8n_worker;
GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO n8n_worker;
```

- [ ] **Step 2: Add `N8N_WORKER_PASSWORD` to `.env.example`**

Append these lines to `.env.example`:

```env
N8N_WORKER_PASSWORD=changeme_n8n_worker
N8N_WORKER_DATABASE_URL=postgresql://n8n_worker:changeme_n8n_worker@db:5432/fpcollector
```

Also copy the two new lines into your local `.env` file:

```bash
echo 'N8N_WORKER_PASSWORD=changeme_n8n_worker' >> .env
echo 'N8N_WORKER_DATABASE_URL=postgresql://n8n_worker:changeme_n8n_worker@db:5432/fpcollector' >> .env
```

- [ ] **Step 3: Apply the migration to both local databases**

```bash
docker-compose exec -T db psql -U fpcollector -d fpcollector_test \
  -v n8n_worker_password="changeme_n8n_worker" \
  < db/migrations/003_create_n8n_worker_user.sql

docker-compose exec -T db psql -U fpcollector -d fpcollector \
  -v n8n_worker_password="changeme_n8n_worker" \
  < db/migrations/003_create_n8n_worker_user.sql
```

(When psql is invoked without `-c` or `-f`, it reads SQL from stdin. The `-T` flag on `docker-compose exec` passes the redirected file through.)

- [ ] **Step 4: Verify the user exists and can connect**

```bash
docker-compose exec -T db psql -U n8n_worker -d fpcollector -c "SELECT current_user;"
```

When prompted, enter `changeme_n8n_worker`. Expected output: a row showing `current_user = n8n_worker`.

- [ ] **Step 5: Commit**

```bash
git add db/migrations/003_create_n8n_worker_user.sql .env.example
git commit -m "feat: add restricted n8n_worker DB user with least-privilege grants"
```

---

## Task 3: Integration test — n8n_worker permissions

**Files:**
- Create: `api/tests/test_phase2_permissions.py`

This test verifies that `n8n_worker` can do exactly what the workflow needs and nothing more.

- [ ] **Step 1: Write the test**

Create `api/tests/test_phase2_permissions.py`:

```python
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
    # First insert the clean_event this lead will reference
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
```

- [ ] **Step 2: Run the tests**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase2_permissions.py -v
```

Expected: all 8 tests `PASS`. If any test fails with an unexpected privilege, review the grants in `db/migrations/003_create_n8n_worker_user.sql` and re-apply.

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_phase2_permissions.py
git commit -m "feat: verify n8n_worker least-privilege grants via integration tests"
```

---

## Task 4: Network topology decision + docker-compose update

**Files:**
- Modify: `docker-compose.yml`

This task decides HOW the martech-lab n8n reaches the dokploy-lab PostgreSQL. Spec Section 6 lists two options; this task picks one based on the current homelab topology.

- [ ] **Step 1: Inspect the current network topology on dokploy-lab**

SSH to dokploy-lab and run:

```bash
docker network ls
docker network inspect proxy-net | head -30
ip -4 addr show | grep inet
```

Note the server's internal LAN IP (e.g., `10.10.10.20`) and any cross-lab Docker networks already configured.

- [ ] **Step 2: Pick an option**

**Option X (preferred if available):** A Docker network already exists that both labs can join. Usually this would be a shared network created earlier (e.g., `homelab-internal`). Use this if `docker network ls` shows such a network.

**Option Y (fallback):** Bind the `db` service to the dokploy-lab LAN IP. Simpler but requires the martech-lab n8n container to reach that IP directly.

- [ ] **Step 3: Apply the change to `docker-compose.yml`**

**If Option X:** Add the shared network to the `db` service and declare it at the bottom:

```yaml
services:
  db:
    # ... existing fields ...
    networks:
      - internal
      - homelab-internal

networks:
  internal:
    driver: bridge
  proxy-net:
    external: true
  homelab-internal:
    external: true
```

(Replace `homelab-internal` with the actual network name you found in Step 1.)

**If Option Y:** Add a `ports` mapping bound to the LAN IP (not `0.0.0.0`). Replace the `db` service block with:

```yaml
  db:
    image: postgres:16.3
    expose:
      - "5432"
    ports:
      - "10.10.10.20:5432:5432"   # replace with your dokploy-lab LAN IP
    env_file: .env
    volumes:
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $$POSTGRES_USER"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - internal
```

Document your choice in a one-line comment in `docker-compose.yml` above the `db` service.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: expose PostgreSQL to martech-lab n8n via [Option X|Y]"
```

(Replace `[Option X|Y]` with the actual option chosen.)

---

## Task 5: Deploy migrations to dokploy-lab PostgreSQL

**Files:** No files modified — this is a server-side ops task.

- [ ] **Step 1: SSH to dokploy-lab, pull the latest main**

```bash
ssh dokploy-lab
cd /mnt/data/stacks/fp-collector
git pull
```

- [ ] **Step 2: Bring the stack up with the updated config**

```bash
docker compose up -d
```

This picks up any `docker-compose.yml` changes from Task 4.

- [ ] **Step 3: Apply Phase 2 migrations**

Generate a strong password for `n8n_worker` (32+ random chars):
```bash
N8N_PW=$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)
echo "Generated password: $N8N_PW"
echo "N8N_WORKER_PASSWORD=$N8N_PW" >> .env
```

Apply migrations:
```bash
docker compose exec -T db psql -U fpcollector -d fpcollector < db/migrations/002_add_processing_state.sql
docker compose exec -T db psql -U fpcollector -d fpcollector \
  -v n8n_worker_password="$N8N_PW" \
  < db/migrations/003_create_n8n_worker_user.sql
```

- [ ] **Step 4: Verify**

```bash
docker compose exec -T db psql -U fpcollector -d fpcollector -c "\d raw_events" | grep -E "(processed_at|processing_error|idx_raw_events_unprocessed)"
docker compose exec -T db psql -U n8n_worker -d fpcollector -c "SELECT current_user;"
```

Expected: first command shows both new columns and the index; second confirms n8n_worker can log in.

- [ ] **Step 5: Log the generated password in the homelab secret store**

Record `N8N_WORKER_PASSWORD` somewhere persistent (password manager, homelab vault, or the dokploy-lab `.env`). You'll need it for Task 6.

No commit for this task — it's a deployment action, not a code change.

---

## Task 6: Build the n8n workflow

**Files:** No code files — work happens in the n8n UI on martech-lab.

- [ ] **Step 1: Open martech-lab n8n and create a new workflow**

Name it `fp-collector-pipeline`.

- [ ] **Step 2: Create a PostgreSQL credential**

Settings → Credentials → New → PostgreSQL:
- Host: dokploy-lab LAN IP (Option Y) OR container name `db` (Option X)
- Port: 5432
- Database: `fpcollector`
- User: `n8n_worker`
- Password: the `N8N_WORKER_PASSWORD` from Task 5

Save as credential name: `fp-collector-n8n-worker`.

- [ ] **Step 3: Add the Schedule Trigger node**

- Type: Schedule Trigger
- Rule: Every 30 seconds

- [ ] **Step 4: Add the "Fetch unprocessed batch" PostgreSQL node**

- Type: PostgreSQL
- Credential: `fp-collector-n8n-worker`
- Operation: Execute Query
- Query:
  ```sql
  SELECT id, event_id, event_name, occurred_at, session_id, anonymous_id,
         page_url, referrer, utm_source, utm_medium, utm_campaign,
         utm_term, utm_content, fbclid, payload
  FROM raw_events
  WHERE processed_at IS NULL AND processing_error IS NULL
  ORDER BY id
  LIMIT 100
  FOR UPDATE SKIP LOCKED
  ```

Validate by clicking "Execute Node" — it should run without error (likely returns empty until you seed data).

- [ ] **Step 5: Add the "Has rows?" IF node**

- Type: IF
- Condition: `{{ $items().length > 0 }}` is true
- False branch connects to nothing (workflow ends there).

- [ ] **Step 6: Add the "Compute source_medium" Code node**

- Type: Code (JavaScript)
- Code:

```javascript
for (const item of items) {
  const e = item.json;
  let source = null, medium = null;

  if (e.utm_source && e.utm_medium) {
    source = e.utm_source.toLowerCase();
    medium = e.utm_medium.toLowerCase();
  } else if (e.fbclid) {
    source = 'facebook';
    medium = 'cpc';
  } else if (e.referrer) {
    const host = new URL(e.referrer).hostname.toLowerCase().replace(/^www\./, '');
    if (host.includes('google.')) {
      [source, medium] = ['google', 'organic'];
    } else if (host.includes('facebook.') || host.includes('instagram.')) {
      [source, medium] = ['facebook', 'referral'];
    } else if (host.includes('linkedin.')) {
      [source, medium] = ['linkedin', 'referral'];
    } else if (host.includes('twitter.') || host.includes('t.co') || host.includes('x.com')) {
      [source, medium] = ['twitter', 'referral'];
    } else {
      [source, medium] = [host, 'referral'];
    }
  } else {
    [source, medium] = ['direct', 'none'];
  }

  item.json.source_medium = `${source} / ${medium}`;
}

return items;
```

- [ ] **Step 7: Add the "Insert clean_events" PostgreSQL node**

- Type: PostgreSQL
- Credential: `fp-collector-n8n-worker`
- Operation: Execute Query
- Query:
  ```sql
  INSERT INTO clean_events (
      raw_event_id, event_id, event_name, occurred_at, session_id, anonymous_id,
      page_url, referrer, utm_source, utm_medium, utm_campaign, source_medium, payload
  ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
  ON CONFLICT (event_id) DO NOTHING
  ```
- Query parameters (use n8n's `={{ $json.field }}` expression syntax):
  1. `{{ $json.id }}`
  2. `{{ $json.event_id }}`
  3. `{{ $json.event_name }}`
  4. `{{ $json.occurred_at }}`
  5. `{{ $json.session_id }}`
  6. `{{ $json.anonymous_id }}`
  7. `{{ $json.page_url }}`
  8. `{{ $json.referrer }}`
  9. `{{ $json.utm_source }}`
  10. `{{ $json.utm_medium }}`
  11. `{{ $json.utm_campaign }}`
  12. `{{ $json.source_medium }}`
  13. `{{ JSON.stringify($json.payload) }}`

- Settings → On Error: **Continue (using error output)**

- [ ] **Step 8: Add the "Is form_submit?" IF node**

- Type: IF
- Condition: `{{ $json.event_name }}` equals `form_submit`

- [ ] **Step 9: Add the "Insert lead" PostgreSQL node (true branch)**

- Type: PostgreSQL
- Credential: `fp-collector-n8n-worker`
- Operation: Execute Query
- Query:
  ```sql
  INSERT INTO leads (event_id, anonymous_id, occurred_at, utm_source, utm_medium, utm_campaign, payload)
  VALUES ($1, $2, $3, $4, $5, $6, $7)
  ```
- Parameters:
  1. `{{ $json.event_id }}`
  2. `{{ $json.anonymous_id }}`
  3. `{{ $json.occurred_at }}`
  4. `{{ $json.utm_source }}`
  5. `{{ $json.utm_medium }}`
  6. `{{ $json.utm_campaign }}`
  7. `{{ JSON.stringify($json.payload) }}`

- Settings → On Error: **Continue (using error output)**

- [ ] **Step 10: Add the "Mark as processed" PostgreSQL node**

Connect to the false branch of the "Is form_submit?" IF **and** the output of "Insert lead" (merge via a NoOp node or connect both into the same input).

- Type: PostgreSQL
- Credential: `fp-collector-n8n-worker`
- Operation: Execute Query
- Query:
  ```sql
  UPDATE raw_events SET processed_at = now() WHERE id = ANY($1::bigint[])
  ```
- Parameters:
  1. `{{ $items().map(i => i.json.id) }}`

- [ ] **Step 11: Add the error handler branch**

Create a "Set processing_error" PostgreSQL node connected to the error outputs of steps 7 and 9:

- Type: PostgreSQL
- Credential: `fp-collector-n8n-worker`
- Operation: Execute Query
- Query:
  ```sql
  UPDATE raw_events SET processing_error = $2 WHERE id = $1
  ```
- Parameters:
  1. `{{ $json.id }}`
  2. `{{ $json.error?.message || 'unknown error' }}`

- [ ] **Step 12: Activate the workflow**

Toggle the workflow to **Active** in the top-right of the n8n canvas. This starts the schedule trigger.

- [ ] **Step 13: Validate by eye**

On dokploy-lab, in a psql session:
```bash
docker compose exec -T db psql -U fpcollector -d fpcollector -c "
  SELECT COUNT(*) FILTER (WHERE processed_at IS NULL AND processing_error IS NULL) AS pending,
         COUNT(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
         COUNT(*) FILTER (WHERE processing_error IS NOT NULL) AS failed
  FROM raw_events;
"
```

If Phase 1 has already ingested any rows, `pending` should drop to 0 within 30 seconds of activation. `processed` should grow.

No commit for this task — the workflow lives in n8n. The export comes in Task 8.

---

## Task 7: End-to-end smoke test

**Files:**
- Create: `api/tests/test_phase2_smoke.py`

This test validates the full pipeline by inserting a batch of events, waiting for the workflow to process them, and asserting the results.

**Prerequisites:** the n8n workflow from Task 6 is active and connected to the same DB being tested against.

- [ ] **Step 1: Write the test**

Create `api/tests/test_phase2_smoke.py`:

```python
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest


PIPELINE_WAIT_SECONDS = int(os.environ.get("PHASE2_PIPELINE_WAIT", "45"))


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


@pytest.mark.skipif(
    os.environ.get("PHASE2_SMOKE") != "1",
    reason="Phase 2 smoke test only runs against a live n8n pipeline (set PHASE2_SMOKE=1)",
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

    await asyncio.sleep(PIPELINE_WAIT_SECONDS)

    event_ids = [e["event_id"] for e in events]
    async with db_pool.acquire() as conn:
        # All three raw_events marked processed
        rows = await conn.fetch(
            "SELECT event_id, processed_at, processing_error FROM raw_events WHERE event_id = ANY($1)",
            event_ids,
        )
        assert len(rows) == 3
        for r in rows:
            assert r["processed_at"] is not None, f"not processed: {r['event_id']}"
            assert r["processing_error"] is None, f"has error: {r['processing_error']}"

        # All three clean_events exist with correct source_medium
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

        # Lead was created for the form_submit only
        leads = await conn.fetch(
            "SELECT event_id, payload FROM leads WHERE event_id = ANY($1)",
            event_ids,
        )
        assert len(leads) == 1
        assert leads[0]["event_id"] == events[2]["event_id"]
        assert leads[0]["payload"]["email"] == "smoke@example.com"
```

- [ ] **Step 2: Run the smoke test against a live pipeline**

The smoke test has to run against the same database the n8n workflow is writing to. Because the workflow runs on martech-lab and targets dokploy-lab's `fpcollector` DB (not `fpcollector_test`), run this from dokploy-lab:

```bash
ssh dokploy-lab
cd /mnt/data/stacks/fp-collector
docker compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector \
  -e PHASE2_SMOKE=1 \
  api python -m pytest tests/test_phase2_smoke.py -v -s
```

The test seeds 3 events, waits 45s, and asserts the pipeline processed everything correctly. Expected: `PASSED`.

If the test fails:
- Check n8n execution history on martech-lab for error details
- Query `raw_events` directly to see which rows got stuck and why

- [ ] **Step 3: Commit**

```bash
git add api/tests/test_phase2_smoke.py
git commit -m "feat: add Phase 2 end-to-end pipeline smoke test"
```

---

## Task 8: Export workflow JSON + commit

**Files:**
- Create: `n8n/workflows/fp-collector-pipeline.json`

- [ ] **Step 1: Export the workflow from n8n**

In the n8n UI:
- Open the `fp-collector-pipeline` workflow
- Click the menu (`…`) → **Download**
- Save the file as `fp-collector-pipeline.json`

- [ ] **Step 2: Move the exported file to the repo**

```bash
mkdir -p n8n/workflows
mv ~/Downloads/fp-collector-pipeline.json n8n/workflows/fp-collector-pipeline.json
```

(Adjust the source path if your browser saves elsewhere.)

- [ ] **Step 3: Sanity-check the JSON**

Verify the export does NOT contain the credential password:
```bash
grep -i "password" n8n/workflows/fp-collector-pipeline.json
```

Expected: no matches, or only credential *names* (not values). If a password appears, redact it manually and note the concern.

- [ ] **Step 4: Commit**

```bash
git add n8n/workflows/fp-collector-pipeline.json
git commit -m "feat: add exported n8n workflow (fp-collector-pipeline)"
```

---

## Task 9: Write n8n README

**Files:**
- Create: `n8n/README.md`

- [ ] **Step 1: Create `n8n/README.md`**

```markdown
# n8n Workflow — fp-collector-pipeline

## Purpose

Processes rows from `raw_events`, enriches them with a derived `source_medium`,
writes normalized rows to `clean_events`, and creates `leads` rows from
`form_submit` events.

- Trigger: Schedule, every 30 seconds
- Batch size: 100 rows
- Latency target: p95 < 60s

## Import

1. In the n8n UI: Workflows → Import from File → pick
   `n8n/workflows/fp-collector-pipeline.json`.
2. Create a PostgreSQL credential named `fp-collector-n8n-worker`:
   - Host: dokploy-lab PostgreSQL host (shared Docker network name or LAN IP)
   - Port: 5432
   - Database: `fpcollector`
   - User: `n8n_worker`
   - Password: value of `N8N_WORKER_PASSWORD` from the dokploy-lab `.env`
3. Assign the credential to every PostgreSQL node in the workflow.
4. Activate the workflow.

## Attribution Rules (source_medium)

The workflow derives `source_medium` for each event using the following
priority order:

1. **UTM present** — use `utm_source / utm_medium` (lowercased).
2. **fbclid present (no UTM)** — `facebook / cpc` (Meta ads click).
3. **Referrer present** — mapped from the referrer hostname:
   - `google.*` → `google / organic`
   - `facebook.*`, `instagram.*` → `facebook / referral`
   - `linkedin.*` → `linkedin / referral`
   - `twitter.*`, `t.co`, `x.com` → `twitter / referral`
   - anything else → `<hostname> / referral`
4. **None of the above** — `direct / none`.

## MVP Simplifications

- No `gclid` handling — UTMs cover Google Ads in practice.
- `google / organic` vs `google / cpc` distinction requires UTM tagging.
- Referrer categorization uses simple substring matching.
- No lead deduplication; each `form_submit` creates a new `leads` row.

## Operations

**Retry failed rows:**

```sql
UPDATE raw_events SET processing_error = NULL WHERE processing_error LIKE '%pattern%';
```

**Full backfill:**

```sql
UPDATE raw_events SET processed_at = NULL, processing_error = NULL;
```

The `ON CONFLICT DO NOTHING` on `clean_events` makes re-processing idempotent.

**Monitoring:**

- n8n execution history shows failed runs.
- Dead-letter rows: `SELECT * FROM raw_events WHERE processing_error IS NOT NULL`.
```

- [ ] **Step 2: Commit**

```bash
git add n8n/README.md
git commit -m "docs: add n8n workflow README with import guide and attribution rules"
```

---

## Final Verification

- [ ] **Step 1: Confirm all tests pass**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase2_schema.py tests/test_phase2_permissions.py -v
```

Expected: all tests `PASS`. (The smoke test in `test_phase2_smoke.py` requires a live pipeline and is gated behind `PHASE2_SMOKE=1`; run it from dokploy-lab per Task 7.)

- [ ] **Step 2: Confirm the pipeline is live on martech-lab**

Open the n8n UI, verify `fp-collector-pipeline` shows status **Active**, and the last execution is recent (within the last 30s).

- [ ] **Step 3: Confirm no rows are stuck**

```bash
docker compose exec -T db psql -U fpcollector -d fpcollector -c "
  SELECT COUNT(*) FILTER (WHERE processed_at IS NULL AND processing_error IS NULL) AS pending,
         COUNT(*) FILTER (WHERE processing_error IS NOT NULL) AS failed
  FROM raw_events;
"
```

Expected: `pending` is 0 or very low (just-ingested rows), `failed` is 0.

Phase 2 is complete when all three verifications pass.
