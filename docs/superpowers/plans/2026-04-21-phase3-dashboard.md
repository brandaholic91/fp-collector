# fp-collector Phase 3 — Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four `GET /api/stats/*` endpoints plus the dashboard UI at `/dashboard` — pipeline health KPIs, conversion funnel, time-series events chart, and UTM breakdown table — with preset time range filtering.

**Architecture:** Four FastAPI route handlers in a new `api/routes/stats.py`, each running a single asyncpg query against `raw_events` or `clean_events`. A single-page vanilla JS dashboard in `api/static/dashboard/` using Tailwind and Chart.js via CDN. All endpoints accept optional `from`/`to` ISO timestamp query parameters.

**Tech Stack:** Python 3.12, FastAPI 0.115, asyncpg 0.29, Pydantic v2, Tailwind CSS (CDN), Chart.js 4.4.x (CDN), Vanilla JS

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `api/models.py` | Modify | Add `HealthResponse`, `FunnelResponse`, `EventsResponse`, `UtmResponse` Pydantic models |
| `api/routes/stats.py` | Create | Four route handlers: `/api/stats/health`, `/funnel`, `/events`, `/utm` |
| `api/main.py` | Modify | Add `app.include_router(stats.router)` |
| `api/static/dashboard/index.html` | Modify | Replace Phase 1 placeholder with Tailwind + Chart.js scaffold |
| `api/static/dashboard/app.js` | Create | Fetch + render logic, preset state |
| `api/tests/test_phase3_stats.py` | Create | Integration tests for all four stats endpoints |

---

## Prerequisites

Before starting, the following must be true:

1. Phase 1 and Phase 2 are merged to `main`. The `raw_events`, `clean_events`, `leads` tables exist with the Phase 2 schema extensions (`processed_at`, `processing_error` columns).
2. Local Docker stack starts cleanly: `docker-compose up -d`.
3. `fpcollector_test` test database exists and has the schema:
   ```bash
   docker-compose up -d db
   docker-compose exec db psql -U fpcollector -c "CREATE DATABASE fpcollector_test;"
   docker-compose exec -T db psql -U fpcollector -d fpcollector_test < db/init.sql
   ```

## How tests run

Phase 3 tests run **inside the `api` container** (same pattern as Phase 2). Standard test run command used throughout:

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/<file> -v
```

Between test runs, the existing `clean_db` autouse fixture in `api/tests/conftest.py` TRUNCATEs all three tables, so each test starts with empty data.

If the `db/` directory isn't already copied into the api container from earlier work, run once:

```bash
docker cp db $(docker-compose ps -q api):/db
```

Also copy the updated source files into the container whenever they change, since the Phase 1 Dockerfile does `COPY . .` at build time but local edits don't propagate without rebuild:

```bash
docker cp api/<file> $(docker-compose ps -q api):/app/<file>
```

These dev-copied files persist across `docker-compose restart api` but are lost on `docker-compose down && up`. Rebuild the image (`docker-compose build api`) if you want them baked in.

---

## Task 1: Health endpoint (GET /api/stats/health)

**Files:**
- Modify: `api/models.py`
- Create: `api/routes/stats.py`
- Modify: `api/main.py`
- Create: `api/tests/test_phase3_stats.py`

- [ ] **Step 1: Write the failing tests**

Create `api/tests/test_phase3_stats.py`:

```python
import uuid
from datetime import datetime, timedelta, timezone

import pytest


async def _insert_raw(conn, event_name="page_view", occurred_at=None,
                     processed=False, failed=False):
    occurred_at = occurred_at or datetime.now(timezone.utc)
    processed_at = occurred_at if processed else None
    processing_error = "test error" if failed else None
    await conn.execute(
        """
        INSERT INTO raw_events (
            event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, consent_analytics, payload, processed_at, processing_error
        ) VALUES ($1, $2, $3, 'sess', 'anon', 'https://x/', true, '{}', $4, $5)
        """,
        uuid.uuid4(), event_name, occurred_at, processed_at, processing_error,
    )


@pytest.mark.asyncio
async def test_health_returns_zeros_for_empty_db(client):
    response = await client.get("/api/stats/health")
    assert response.status_code == 200
    assert response.json() == {
        "ingested": 0,
        "duplicates": 0,
        "duplicate_rate": 0.0,
        "processed": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_health_counts_ingested_processed_failed(client, db_pool):
    async with db_pool.acquire() as conn:
        await _insert_raw(conn)                      # pending
        await _insert_raw(conn, processed=True)      # processed
        await _insert_raw(conn, processed=True)      # processed
        await _insert_raw(conn, failed=True)         # failed

    response = await client.get("/api/stats/health")
    data = response.json()
    assert data["ingested"] == 4
    assert data["processed"] == 2
    assert data["failed"] == 1
    assert data["duplicates"] == 0
    assert data["duplicate_rate"] == 0.0


@pytest.mark.asyncio
async def test_health_respects_time_range_filter(client, db_pool):
    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_raw(conn, occurred_at=now - timedelta(days=10))
        await _insert_raw(conn, occurred_at=now - timedelta(days=1))
        await _insert_raw(conn, occurred_at=now)

    from_ts = (now - timedelta(days=2)).isoformat()
    response = await client.get(f"/api/stats/health?from={from_ts}")
    assert response.json()["ingested"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -v
```

Expected: all three tests `FAIL` with `404 Not Found` (endpoint does not exist).

- [ ] **Step 3: Add response model to `api/models.py`**

Append to `api/models.py`:

```python
class HealthResponse(BaseModel):
    ingested: int
    duplicates: int
    duplicate_rate: float
    processed: int
    failed: int
```

- [ ] **Step 4: Create `api/routes/stats.py`**

```python
from datetime import datetime
from typing import Optional

from asyncpg import Pool
from fastapi import APIRouter, Depends, Query

from db import get_pool
from models import HealthResponse

router = APIRouter(prefix="/api/stats")


def _range_filter(column: str, from_: Optional[datetime], to: Optional[datetime]):
    clauses, params = [], []
    if from_ is not None:
        params.append(from_)
        clauses.append(f"{column} >= ${len(params)}")
    if to is not None:
        params.append(to)
        clauses.append(f"{column} <= ${len(params)}")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@router.get("/health", response_model=HealthResponse)
async def stats_health(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT
            COUNT(*) AS ingested,
            COUNT(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
            COUNT(*) FILTER (WHERE processing_error IS NOT NULL) AS failed
        FROM raw_events
        {where}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)
    return HealthResponse(
        ingested=row["ingested"],
        duplicates=0,
        duplicate_rate=0.0,
        processed=row["processed"],
        failed=row["failed"],
    )
```

- [ ] **Step 5: Register the router in `api/main.py`**

Edit `api/main.py`. Add next to the existing `from routes import events` line:

```python
from routes import events, stats
```

And add next to the existing `app.include_router(events.router)` line:

```python
app.include_router(stats.router)
```

- [ ] **Step 6: Copy updated files into the container**

```bash
docker cp api/models.py $(docker-compose ps -q api):/app/models.py
docker cp api/routes/stats.py $(docker-compose ps -q api):/app/routes/stats.py
docker cp api/main.py $(docker-compose ps -q api):/app/main.py
docker cp api/tests/test_phase3_stats.py $(docker-compose ps -q api):/app/tests/test_phase3_stats.py
docker-compose restart api
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -v
```

Expected: all three tests `PASS`.

- [ ] **Step 8: Commit**

```bash
git add api/models.py api/routes/stats.py api/main.py api/tests/test_phase3_stats.py
git commit -m "feat: add GET /api/stats/health endpoint with time range filtering"
```

---

## Task 2: Funnel endpoint (GET /api/stats/funnel)

**Files:**
- Modify: `api/models.py`
- Modify: `api/routes/stats.py`
- Modify: `api/tests/test_phase3_stats.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_phase3_stats.py`:

```python
async def _insert_clean(conn, event_name, anonymous_id,
                        occurred_at=None, utm_source=None,
                        utm_medium=None, utm_campaign=None,
                        source_medium="direct / none"):
    occurred_at = occurred_at or datetime.now(timezone.utc)
    event_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO clean_events (
            event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, utm_source, utm_medium, utm_campaign,
            source_medium, payload
        ) VALUES ($1, $2, $3, 'sess', $4, 'https://x/', $5, $6, $7, $8, '{}')
        """,
        event_id, event_name, occurred_at, anonymous_id,
        utm_source, utm_medium, utm_campaign, source_medium,
    )
    return event_id


@pytest.mark.asyncio
async def test_funnel_returns_zero_counts_for_empty_db(client):
    response = await client.get("/api/stats/funnel")
    assert response.status_code == 200
    steps = response.json()["steps"]
    assert [s["event_name"] for s in steps] == ["page_view", "cta_click", "form_submit"]
    for step in steps:
        assert step["count"] == 0
        assert step["conversion_from_top"] is None


@pytest.mark.asyncio
async def test_funnel_counts_distinct_anonymous_per_step(client, db_pool):
    async with db_pool.acquire() as conn:
        for anon in ["a", "b", "c", "d"]:
            await _insert_clean(conn, "page_view", anon)
        await _insert_clean(conn, "page_view", "a")  # repeat → still 4 distinct
        for anon in ["a", "b"]:
            await _insert_clean(conn, "cta_click", anon)
        await _insert_clean(conn, "form_submit", "a")

    response = await client.get("/api/stats/funnel")
    steps = {s["event_name"]: s for s in response.json()["steps"]}
    assert steps["page_view"]["count"] == 4
    assert steps["page_view"]["conversion_from_top"] == 1.0
    assert steps["cta_click"]["count"] == 2
    assert steps["cta_click"]["conversion_from_top"] == 0.5
    assert steps["form_submit"]["count"] == 1
    assert steps["form_submit"]["conversion_from_top"] == 0.25
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker cp api/tests/test_phase3_stats.py $(docker-compose ps -q api):/app/tests/test_phase3_stats.py
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -k "funnel" -v
```

Expected: both funnel tests `FAIL` with `404 Not Found`.

- [ ] **Step 3: Add the response model**

Append to `api/models.py`:

```python
class FunnelStep(BaseModel):
    event_name: str
    count: int
    conversion_from_top: Optional[float]


class FunnelResponse(BaseModel):
    steps: list[FunnelStep]
```

Add `Optional` to the existing `from typing import Literal, Optional` import if it isn't already there.

- [ ] **Step 4: Add the route to `api/routes/stats.py`**

Append to `api/routes/stats.py`:

```python
from models import FunnelResponse, FunnelStep

FUNNEL_STEPS = ["page_view", "cta_click", "form_submit"]


@router.get("/funnel", response_model=FunnelResponse)
async def stats_funnel(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT event_name, COUNT(DISTINCT anonymous_id) AS count
        FROM clean_events
        {where}
        GROUP BY event_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    counts = {r["event_name"]: r["count"] for r in rows}

    top = counts.get(FUNNEL_STEPS[0], 0)
    steps = []
    for name in FUNNEL_STEPS:
        count = counts.get(name, 0)
        conv = (count / top) if top > 0 else None
        steps.append(FunnelStep(event_name=name, count=count, conversion_from_top=conv))
    return FunnelResponse(steps=steps)
```

Move the `from models import ...` line near the top so all imports are together (keep a single import line, e.g., `from models import HealthResponse, FunnelResponse, FunnelStep`). Update the import at the top of `stats.py`:

```python
from models import HealthResponse, FunnelResponse, FunnelStep
```

And remove the duplicate `from models import FunnelResponse, FunnelStep` line if you pasted it.

- [ ] **Step 5: Copy updated files and run tests**

```bash
docker cp api/models.py $(docker-compose ps -q api):/app/models.py
docker cp api/routes/stats.py $(docker-compose ps -q api):/app/routes/stats.py
docker-compose restart api
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -k "funnel" -v
```

Expected: both funnel tests `PASS`.

- [ ] **Step 6: Commit**

```bash
git add api/models.py api/routes/stats.py api/tests/test_phase3_stats.py
git commit -m "feat: add GET /api/stats/funnel endpoint with conversion_from_top"
```

---

## Task 3: Events time-series endpoint (GET /api/stats/events)

**Files:**
- Modify: `api/models.py`
- Modify: `api/routes/stats.py`
- Modify: `api/tests/test_phase3_stats.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_phase3_stats.py`:

```python
@pytest.mark.asyncio
async def test_events_returns_empty_series_for_empty_db(client):
    response = await client.get("/api/stats/events")
    assert response.status_code == 200
    assert response.json() == {"series": []}


@pytest.mark.asyncio
async def test_events_groups_by_day_and_event_name(client, db_pool):
    day1 = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_clean(conn, "page_view", "a", occurred_at=day1)
        await _insert_clean(conn, "page_view", "b", occurred_at=day1)
        await _insert_clean(conn, "cta_click", "a", occurred_at=day1)
        await _insert_clean(conn, "page_view", "c", occurred_at=day2)

    response = await client.get("/api/stats/events")
    series = response.json()["series"]
    rows = {(r["date"], r["event_name"]): r["count"] for r in series}
    assert rows[("2026-04-10", "page_view")] == 2
    assert rows[("2026-04-10", "cta_click")] == 1
    assert rows[("2026-04-11", "page_view")] == 1
    assert len(series) == 3


@pytest.mark.asyncio
async def test_events_respects_time_range_filter(client, db_pool):
    old = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    new = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_clean(conn, "page_view", "a", occurred_at=old)
        await _insert_clean(conn, "page_view", "b", occurred_at=new)

    response = await client.get("/api/stats/events?from=2026-04-01T00:00:00Z")
    series = response.json()["series"]
    assert len(series) == 1
    assert series[0]["date"] == "2026-04-10"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker cp api/tests/test_phase3_stats.py $(docker-compose ps -q api):/app/tests/test_phase3_stats.py
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -k "events" -v
```

Expected: all three events tests `FAIL`.

- [ ] **Step 3: Add response model**

Append to `api/models.py`:

```python
class EventSeriesRow(BaseModel):
    date: str
    event_name: str
    count: int


class EventsResponse(BaseModel):
    series: list[EventSeriesRow]
```

- [ ] **Step 4: Add the route**

Append to `api/routes/stats.py` and update the existing models import at the top:

```python
from models import HealthResponse, FunnelResponse, FunnelStep, EventsResponse, EventSeriesRow
```

Add the handler:

```python
@router.get("/events", response_model=EventsResponse)
async def stats_events(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT
            date_trunc('day', occurred_at)::date AS date,
            event_name,
            COUNT(*) AS count
        FROM clean_events
        {where}
        GROUP BY date, event_name
        ORDER BY date, event_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    series = [
        EventSeriesRow(
            date=r["date"].isoformat(),
            event_name=r["event_name"],
            count=r["count"],
        )
        for r in rows
    ]
    return EventsResponse(series=series)
```

- [ ] **Step 5: Copy and run tests**

```bash
docker cp api/models.py $(docker-compose ps -q api):/app/models.py
docker cp api/routes/stats.py $(docker-compose ps -q api):/app/routes/stats.py
docker-compose restart api
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -k "events" -v
```

Expected: all three tests `PASS`.

- [ ] **Step 6: Commit**

```bash
git add api/models.py api/routes/stats.py api/tests/test_phase3_stats.py
git commit -m "feat: add GET /api/stats/events endpoint with daily time-series grouping"
```

---

## Task 4: UTM breakdown endpoint (GET /api/stats/utm)

**Files:**
- Modify: `api/models.py`
- Modify: `api/routes/stats.py`
- Modify: `api/tests/test_phase3_stats.py`

- [ ] **Step 1: Write the failing tests**

Append to `api/tests/test_phase3_stats.py`:

```python
@pytest.mark.asyncio
async def test_utm_returns_empty_rows_for_empty_db(client):
    response = await client.get("/api/stats/utm")
    assert response.status_code == 200
    assert response.json() == {"rows": []}


@pytest.mark.asyncio
async def test_utm_aggregates_events_and_joins_leads(client, db_pool):
    async with db_pool.acquire() as conn:
        # Two google/cpc events, one of which has a lead
        google_event_id = await _insert_clean(
            conn, "form_submit", "a",
            utm_source="google", utm_medium="cpc", utm_campaign="spring",
        )
        await _insert_clean(
            conn, "page_view", "b",
            utm_source="google", utm_medium="cpc", utm_campaign="spring",
        )
        # Direct traffic (no UTM)
        await _insert_clean(conn, "page_view", "c")
        # Facebook social, no lead
        await _insert_clean(
            conn, "cta_click", "d",
            utm_source="facebook", utm_medium="social",
        )
        # Insert one lead referencing the google form_submit
        await conn.execute(
            """
            INSERT INTO leads (event_id, anonymous_id, occurred_at, payload)
            VALUES ($1, 'a', now(), '{}')
            """,
            google_event_id,
        )

    response = await client.get("/api/stats/utm")
    rows = response.json()["rows"]
    by_key = {(r["utm_source"], r["utm_medium"]): r for r in rows}

    assert by_key[("google", "cpc")]["events"] == 2
    assert by_key[("google", "cpc")]["leads"] == 1
    assert by_key[("facebook", "social")]["events"] == 1
    assert by_key[("facebook", "social")]["leads"] == 0
    assert by_key[(None, None)]["events"] == 1
    assert by_key[(None, None)]["leads"] == 0


@pytest.mark.asyncio
async def test_utm_rows_sorted_by_events_desc(client, db_pool):
    async with db_pool.acquire() as conn:
        for _ in range(3):
            await _insert_clean(conn, "page_view", uuid.uuid4().hex,
                                utm_source="big", utm_medium="cpc")
        await _insert_clean(conn, "page_view", "x",
                            utm_source="small", utm_medium="cpc")

    response = await client.get("/api/stats/utm")
    rows = response.json()["rows"]
    assert rows[0]["utm_source"] == "big"
    assert rows[0]["events"] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker cp api/tests/test_phase3_stats.py $(docker-compose ps -q api):/app/tests/test_phase3_stats.py
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -k "utm" -v
```

Expected: all three tests `FAIL`.

- [ ] **Step 3: Add the response model**

Append to `api/models.py`:

```python
class UtmRow(BaseModel):
    utm_source: Optional[str]
    utm_medium: Optional[str]
    events: int
    leads: int


class UtmResponse(BaseModel):
    rows: list[UtmRow]
```

- [ ] **Step 4: Add the route**

Update the models import at the top of `api/routes/stats.py`:

```python
from models import (
    HealthResponse, FunnelResponse, FunnelStep,
    EventsResponse, EventSeriesRow,
    UtmResponse, UtmRow,
)
```

Append the handler:

```python
@router.get("/utm", response_model=UtmResponse)
async def stats_utm(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("c.occurred_at", from_, to)
    query = f"""
        SELECT
            c.utm_source,
            c.utm_medium,
            COUNT(*) AS events,
            COUNT(DISTINCT l.id) AS leads
        FROM clean_events c
        LEFT JOIN leads l ON l.event_id = c.event_id
        {where}
        GROUP BY c.utm_source, c.utm_medium
        ORDER BY events DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return UtmResponse(rows=[
        UtmRow(
            utm_source=r["utm_source"],
            utm_medium=r["utm_medium"],
            events=r["events"],
            leads=r["leads"],
        )
        for r in rows
    ])
```

- [ ] **Step 5: Copy and run all stats tests**

```bash
docker cp api/models.py $(docker-compose ps -q api):/app/models.py
docker cp api/routes/stats.py $(docker-compose ps -q api):/app/routes/stats.py
docker-compose restart api
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/test_phase3_stats.py -v
```

Expected: all Phase 3 tests `PASS`.

- [ ] **Step 6: Commit**

```bash
git add api/models.py api/routes/stats.py api/tests/test_phase3_stats.py
git commit -m "feat: add GET /api/stats/utm endpoint with leads LEFT JOIN"
```

---

## Task 5: Dashboard HTML scaffold

**Files:**
- Modify: `api/static/dashboard/index.html`

No automated tests — manual visual verification.

- [ ] **Step 1: Replace `api/static/dashboard/index.html`**

Overwrite the file with:

```html
<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>fp-collector dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7"></script>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen">
  <header class="max-w-6xl mx-auto px-6 pt-8 pb-4 flex items-baseline justify-between">
    <h1 class="text-2xl font-semibold tracking-tight">fp-collector</h1>
    <nav id="preset-nav" class="flex gap-1 text-sm">
      <button data-range="24h" class="preset-btn px-3 py-1.5 rounded-md text-slate-600 hover:bg-slate-200">24h</button>
      <button data-range="7d"  class="preset-btn px-3 py-1.5 rounded-md text-slate-600 hover:bg-slate-200">7d</button>
      <button data-range="30d" class="preset-btn px-3 py-1.5 rounded-md bg-slate-900 text-white">30d</button>
      <button data-range="all" class="preset-btn px-3 py-1.5 rounded-md text-slate-600 hover:bg-slate-200">All</button>
    </nav>
  </header>

  <main class="max-w-6xl mx-auto px-6 py-4 space-y-6">
    <section>
      <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-3">Pipeline Health</h2>
      <div id="health-cards" class="grid grid-cols-4 gap-4">
        <div class="bg-white rounded-xl p-5 shadow-sm">
          <div class="text-xs text-slate-500 uppercase tracking-wide">Ingested</div>
          <div class="mt-2 text-3xl font-semibold tabular-nums" data-metric="ingested">—</div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-sm">
          <div class="text-xs text-slate-500 uppercase tracking-wide">Duplicates</div>
          <div class="mt-2 text-3xl font-semibold tabular-nums" data-metric="duplicates">—</div>
          <div class="text-xs text-slate-500 mt-1" data-metric="duplicate_rate"></div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-sm">
          <div class="text-xs text-slate-500 uppercase tracking-wide">Processed</div>
          <div class="mt-2 text-3xl font-semibold tabular-nums" data-metric="processed">—</div>
        </div>
        <div class="bg-white rounded-xl p-5 shadow-sm">
          <div class="text-xs text-slate-500 uppercase tracking-wide">Failed</div>
          <div class="mt-2 text-3xl font-semibold tabular-nums" data-metric="failed">—</div>
        </div>
      </div>
    </section>

    <section class="bg-white rounded-xl p-6 shadow-sm">
      <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-4">Conversion Funnel</h2>
      <div id="funnel-chart" class="h-48">
        <canvas id="funnel-canvas"></canvas>
      </div>
      <div id="funnel-empty" class="hidden text-center text-slate-400 py-8">No data for this range</div>
    </section>

    <div class="grid grid-cols-2 gap-6">
      <section class="bg-white rounded-xl p-6 shadow-sm">
        <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-4">Events by Day</h2>
        <div class="h-64">
          <canvas id="events-canvas"></canvas>
        </div>
        <div id="events-empty" class="hidden text-center text-slate-400 py-8">No data for this range</div>
      </section>

      <section class="bg-white rounded-xl p-6 shadow-sm">
        <h2 class="text-sm font-medium text-slate-500 uppercase tracking-wide mb-4">UTM Source / Medium</h2>
        <div class="overflow-x-auto">
          <table class="min-w-full text-sm">
            <thead class="text-xs text-slate-500 uppercase tracking-wide border-b">
              <tr>
                <th class="text-left font-medium pb-2">Source</th>
                <th class="text-left font-medium pb-2">Medium</th>
                <th class="text-right font-medium pb-2">Events</th>
                <th class="text-right font-medium pb-2">Leads</th>
              </tr>
            </thead>
            <tbody id="utm-tbody" class="divide-y divide-slate-100"></tbody>
          </table>
        </div>
        <div id="utm-empty" class="hidden text-center text-slate-400 py-8">No data for this range</div>
      </section>
    </div>
  </main>

  <script src="/static/dashboard/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Verify the HTML loads without JS errors**

```bash
docker cp api/static/dashboard/index.html $(docker-compose ps -q api):/app/static/dashboard/index.html
```

Open `http://localhost:8000/dashboard` in a browser.

Expected:
- Page loads with the layout visible (placeholders showing "—")
- Tailwind styles applied (no unstyled text)
- Browser console has no errors (Chart.js and Tailwind load from CDN; if blocked, the styling/charts won't work)

- [ ] **Step 3: Commit**

```bash
git add api/static/dashboard/index.html
git commit -m "feat: add dashboard HTML scaffold with Tailwind and Chart.js"
```

---

## Task 6: Dashboard JavaScript (app.js)

**Files:**
- Create: `api/static/dashboard/app.js`

No automated tests — manual verification in browser.

- [ ] **Step 1: Create `api/static/dashboard/app.js`**

```javascript
(function () {
  const PRESETS = {
    '24h': () => ({ from: isoAgo(1 * 3600 * 1000) }),
    '7d':  () => ({ from: isoAgo(7 * 24 * 3600 * 1000) }),
    '30d': () => ({ from: isoAgo(30 * 24 * 3600 * 1000) }),
    'all': () => ({}),
  };

  function isoAgo(ms) { return new Date(Date.now() - ms).toISOString(); }

  function qs(params) {
    const entries = Object.entries(params).filter(([, v]) => v != null);
    return entries.length ? '?' + new URLSearchParams(entries).toString() : '';
  }

  async function fetchJson(path, params) {
    const r = await fetch(path + qs(params));
    if (!r.ok) throw new Error(`${path} returned ${r.status}`);
    return r.json();
  }

  function fmtInt(n) { return new Intl.NumberFormat().format(n); }
  function fmtPct(x) { return (x * 100).toFixed(1) + '%'; }

  // --- Health ---
  function renderHealth(data) {
    document.querySelector('[data-metric="ingested"]').textContent = fmtInt(data.ingested);
    document.querySelector('[data-metric="duplicates"]').textContent = fmtInt(data.duplicates);
    document.querySelector('[data-metric="duplicate_rate"]').textContent =
      data.ingested > 0 ? fmtPct(data.duplicate_rate) : '';
    document.querySelector('[data-metric="processed"]').textContent = fmtInt(data.processed);
    document.querySelector('[data-metric="failed"]').textContent = fmtInt(data.failed);
  }

  // --- Funnel ---
  let funnelChart = null;
  function renderFunnel(data) {
    const empty = data.steps.every(s => s.count === 0);
    document.getElementById('funnel-empty').classList.toggle('hidden', !empty);
    document.getElementById('funnel-chart').classList.toggle('hidden', empty);
    if (empty) return;

    const ctx = document.getElementById('funnel-canvas').getContext('2d');
    if (funnelChart) funnelChart.destroy();
    funnelChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.steps.map(s => s.event_name),
        datasets: [{
          data: data.steps.map(s => s.count),
          backgroundColor: '#2563eb',
          borderRadius: 6,
        }],
      },
      options: {
        indexAxis: 'y',
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const step = data.steps[ctx.dataIndex];
                const conv = step.conversion_from_top != null
                  ? ` (${fmtPct(step.conversion_from_top)})`
                  : '';
                return `${fmtInt(step.count)}${conv}`;
              },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, grid: { color: '#f1f5f9' } },
          y: { grid: { display: false } },
        },
      },
    });
  }

  // --- Events time series ---
  let eventsChart = null;
  function renderEvents(data) {
    const empty = data.series.length === 0;
    document.getElementById('events-empty').classList.toggle('hidden', !empty);
    document.getElementById('events-canvas').classList.toggle('hidden', empty);
    if (empty) return;

    const dates = [...new Set(data.series.map(r => r.date))].sort();
    const names = ['page_view', 'cta_click', 'form_submit'];
    const colors = { page_view: '#2563eb', cta_click: '#0891b2', form_submit: '#16a34a' };
    const byKey = {};
    data.series.forEach(r => { byKey[`${r.date}|${r.event_name}`] = r.count; });

    const datasets = names.map(name => ({
      label: name,
      data: dates.map(d => byKey[`${d}|${name}`] || 0),
      borderColor: colors[name],
      backgroundColor: colors[name],
      tension: 0.25,
      borderWidth: 2,
      pointRadius: 3,
    }));

    const ctx = document.getElementById('events-canvas').getContext('2d');
    if (eventsChart) eventsChart.destroy();
    eventsChart = new Chart(ctx, {
      type: 'line',
      data: { labels: dates, datasets },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } },
        scales: {
          x: { grid: { display: false } },
          y: { beginAtZero: true, grid: { color: '#f1f5f9' } },
        },
      },
    });
  }

  // --- UTM table ---
  function renderUtm(data) {
    const tbody = document.getElementById('utm-tbody');
    const empty = data.rows.length === 0;
    document.getElementById('utm-empty').classList.toggle('hidden', !empty);
    tbody.parentElement.parentElement.classList.toggle('hidden', empty);
    tbody.innerHTML = '';
    if (empty) return;

    for (const row of data.rows) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="py-2">${row.utm_source ?? '<span class="text-slate-400">(direct)</span>'}</td>
        <td class="py-2">${row.utm_medium ?? '<span class="text-slate-400">(direct)</span>'}</td>
        <td class="py-2 text-right tabular-nums">${fmtInt(row.events)}</td>
        <td class="py-2 text-right tabular-nums">${fmtInt(row.leads)}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  // --- Orchestration ---
  async function loadAll(preset) {
    const params = PRESETS[preset]();
    try {
      const [health, funnel, events, utm] = await Promise.all([
        fetchJson('/api/stats/health', params),
        fetchJson('/api/stats/funnel', params),
        fetchJson('/api/stats/events', params),
        fetchJson('/api/stats/utm', params),
      ]);
      renderHealth(health);
      renderFunnel(funnel);
      renderEvents(events);
      renderUtm(utm);
    } catch (err) {
      console.error('Failed to load dashboard data:', err);
    }
  }

  function setActivePreset(btn) {
    document.querySelectorAll('.preset-btn').forEach(b => {
      b.classList.remove('bg-slate-900', 'text-white');
      b.classList.add('text-slate-600', 'hover:bg-slate-200');
    });
    btn.classList.remove('text-slate-600', 'hover:bg-slate-200');
    btn.classList.add('bg-slate-900', 'text-white');
  }

  document.getElementById('preset-nav').addEventListener('click', (e) => {
    const btn = e.target.closest('.preset-btn');
    if (!btn) return;
    setActivePreset(btn);
    loadAll(btn.dataset.range);
  });

  loadAll('30d');
})();
```

- [ ] **Step 2: Copy into container and test manually**

```bash
docker cp api/static/dashboard/app.js $(docker-compose ps -q api):/app/static/dashboard/app.js
```

Open `http://localhost:8000/dashboard` in a browser.

Expected:
- KPI cards show zeroes (empty DB).
- "No data for this range" displayed in funnel/events/UTM sections.
- Preset buttons clickable; clicking them highlights the active one and refetches.
- No console errors.

- [ ] **Step 3: Commit**

```bash
git add api/static/dashboard/app.js
git commit -m "feat: add dashboard app.js with fetch + chart rendering"
```

---

## Task 7: End-to-end manual smoke test

No code changes — verification only.

- [ ] **Step 1: Seed diverse events into the live DB**

```bash
docker-compose exec -T db psql -U fpcollector -d fpcollector <<'SQL'
TRUNCATE raw_events, clean_events, leads RESTART IDENTITY CASCADE;

-- Seed a realistic mix across yesterday and today
INSERT INTO raw_events (event_id, event_name, occurred_at, session_id, anonymous_id, page_url, utm_source, utm_medium, utm_campaign, consent_analytics, payload, processed_at) VALUES
  (gen_random_uuid(), 'page_view',   now() - interval '1 day', 's1', 'a1', 'https://example.com/', 'google',   'cpc',    'spring', true, '{}', now() - interval '1 day'),
  (gen_random_uuid(), 'page_view',   now() - interval '1 day', 's2', 'a2', 'https://example.com/', 'google',   'cpc',    'spring', true, '{}', now() - interval '1 day'),
  (gen_random_uuid(), 'page_view',   now() - interval '1 day', 's3', 'a3', 'https://example.com/', 'facebook', 'social', NULL,     true, '{}', now() - interval '1 day'),
  (gen_random_uuid(), 'page_view',   now(),                    's4', 'a4', 'https://example.com/', NULL,       NULL,     NULL,     true, '{}', now()),
  (gen_random_uuid(), 'cta_click',   now() - interval '1 day', 's1', 'a1', 'https://example.com/', 'google',   'cpc',    'spring', true, '{}', now() - interval '1 day'),
  (gen_random_uuid(), 'cta_click',   now(),                    's4', 'a4', 'https://example.com/', NULL,       NULL,     NULL,     true, '{}', now()),
  (gen_random_uuid(), 'form_submit', now(),                    's1', 'a1', 'https://example.com/thanks', 'google', 'cpc', 'spring', true, '{"email":"demo@test.com"}', now());

-- Mirror into clean_events with source_medium
INSERT INTO clean_events (raw_event_id, event_id, event_name, occurred_at, session_id, anonymous_id, page_url, utm_source, utm_medium, utm_campaign, source_medium, payload)
  SELECT id, event_id, event_name, occurred_at, session_id, anonymous_id, page_url, utm_source, utm_medium, utm_campaign,
    CASE
      WHEN utm_source = 'google'   THEN 'google / cpc'
      WHEN utm_source = 'facebook' THEN 'facebook / social'
      ELSE 'direct / none'
    END,
    payload
  FROM raw_events;

-- One lead from the form_submit
INSERT INTO leads (event_id, anonymous_id, occurred_at, utm_source, utm_medium, utm_campaign, payload)
  SELECT event_id, anonymous_id, occurred_at, utm_source, utm_medium, utm_campaign, payload
  FROM clean_events WHERE event_name = 'form_submit';
SQL
```

- [ ] **Step 2: Verify the dashboard renders the seeded data**

Open `http://localhost:8000/dashboard` in a browser.

Expected with the `30d` preset:
- **Pipeline Health:** Ingested = 7, Processed = 7, Failed = 0, Duplicates = 0.
- **Conversion Funnel:** page_view = 4, cta_click = 2 (50%), form_submit = 1 (25%).
- **Events by Day:** line chart spanning 2 dates; page_view has values on both, cta_click and form_submit present.
- **UTM:** three rows — `google/cpc`, `facebook/social`, `(direct)/(direct)` — with events and the `google/cpc` row showing 1 lead.

- [ ] **Step 3: Test preset switching**

Click `24h`. Expected: counts drop (only events from the last hour remain — depending on seed timing, roughly 3 events).
Click `All`. Expected: same as `30d` for this dataset.

- [ ] **Step 4: Commit**

No files changed. Skip the commit.

---

## Final Verification

- [ ] **Step 1: All automated tests pass**

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector_test \
  api python -m pytest tests/ -v
```

Expected: all Phase 1, Phase 2 (schema + permissions), and Phase 3 tests `PASS`. (Phase 2 smoke test is gated behind `PHASE2_SMOKE=1` and is not expected to run here.)

- [ ] **Step 2: Dashboard renders end-to-end without console errors**

Browser DevTools → Console should be empty (or only have Tailwind's production-use warning from the CDN script).

- [ ] **Step 3: Each of the four endpoints responds successfully**

```bash
for path in health funnel events utm; do
  echo "--- /api/stats/$path ---"
  docker-compose exec -T api python -c "import httpx; r = httpx.get('http://localhost:8000/api/stats/$path'); print(r.status_code, r.json())"
done
```

Expected: each returns `200` with the expected JSON shape.

Phase 3 is complete when all three verifications pass.
