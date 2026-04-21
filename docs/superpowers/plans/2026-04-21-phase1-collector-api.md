# fp-collector Phase 1 — Collector API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the end-to-end event ingest pipeline: Docker stack, PostgreSQL schema, FastAPI collector API, and the landing page with client tracking script.

**Architecture:** A single FastAPI application running in Docker Compose alongside PostgreSQL. The API validates incoming events, gates on consent, and writes to `raw_events` with idempotency via `ON CONFLICT DO NOTHING`. Static files (landing page + `tracker.js`) are served from FastAPI's `StaticFiles` mount.

**Tech Stack:** Python 3.12, FastAPI 0.115, asyncpg 0.29, Pydantic v2, slowapi 0.1.9, PostgreSQL 16.3, Vanilla JS, Docker Compose

---

## File Map

| File | Responsibility |
|---|---|
| `docker-compose.yml` | Defines `api` and `db` services, networks |
| `.env.example` | Documents required env vars |
| `api/Dockerfile` | Builds the API container image |
| `api/requirements.txt` | Python dependencies |
| `api/config.py` | Loads env vars via pydantic-settings |
| `api/db.py` | asyncpg connection pool lifecycle |
| `api/models.py` | Pydantic request/response models |
| `api/routes/events.py` | `POST /v1/events` handler |
| `api/limiter.py` | Shared slowapi Limiter instance |
| `api/main.py` | FastAPI app, mounts routes and static files |
| `api/static/landing/index.html` | Landing page HTML |
| `api/static/landing/tracker.js` | Client-side event tracking script |
| `db/init.sql` | `CREATE TABLE` statements |
| `api/tests/conftest.py` | pytest fixtures: test DB pool, async HTTP client |
| `api/tests/test_events.py` | Integration tests for `POST /v1/events` |

---

## Task 1: Docker Compose + environment scaffold

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Create `docker-compose.yml`**

```yaml
services:
  api:
    build: ./api
    image: fp-collector-api:1.0.0
    expose:
      - "8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    networks:
      - internal
      - proxy-net

  db:
    image: postgres:16.3
    expose:
      - "5432"
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

networks:
  internal:
    driver: bridge
  proxy-net:
    external: true
```

- [ ] **Step 2: Create `.env.example`**

```env
POSTGRES_USER=fpcollector
POSTGRES_PASSWORD=changeme
POSTGRES_DB=fpcollector
DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector
RATE_LIMIT_PER_MINUTE=100
```

- [ ] **Step 3: Create `.gitignore`**

```
.env
data/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 4: Create `.env` from example (not committed)**

```bash
cp .env.example .env
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example .gitignore
git commit -m "feat: add Docker Compose scaffold and env template"
```

---

## Task 2: Database init SQL

**Files:**
- Create: `db/init.sql`

- [ ] **Step 1: Create `db/init.sql`**

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
    payload           JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_raw_events_occurred_at ON raw_events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_event_name  ON raw_events (event_name);
CREATE INDEX IF NOT EXISTS idx_raw_events_session_id  ON raw_events (session_id);

CREATE TABLE IF NOT EXISTS clean_events (
    id            BIGSERIAL   PRIMARY KEY,
    raw_event_id  BIGINT      REFERENCES raw_events(id),
    event_id      UUID        NOT NULL UNIQUE,
    event_name    TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    session_id    TEXT        NOT NULL,
    anonymous_id  TEXT        NOT NULL,
    page_url      TEXT        NOT NULL,
    referrer      TEXT,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    source_medium TEXT,
    payload       JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS leads (
    id            BIGSERIAL   PRIMARY KEY,
    event_id      UUID        REFERENCES clean_events(event_id),
    anonymous_id  TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    payload       JSONB       NOT NULL DEFAULT '{}'
);
```

- [ ] **Step 2: Commit**

```bash
git add db/init.sql
git commit -m "feat: add PostgreSQL schema (raw_events, clean_events, leads)"
```

---

## Task 3: API Dockerfile + requirements

**Files:**
- Create: `api/Dockerfile`
- Create: `api/requirements.txt`

- [ ] **Step 1: Create `api/requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
asyncpg==0.29.0
pydantic==2.8.2
pydantic-settings==2.3.4
slowapi==0.1.9
pytest==8.3.2
pytest-asyncio==0.23.8
httpx==0.27.2
```

- [ ] **Step 2: Create `api/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Commit**

```bash
git add api/Dockerfile api/requirements.txt
git commit -m "feat: add API Dockerfile and Python dependencies"
```

---

## Task 4: Config + FastAPI skeleton

**Files:**
- Create: `api/config.py`
- Create: `api/main.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/__init__.py` (empty) and `api/tests/conftest.py`:

```python
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
        yield c
```

Create `api/tests/test_events.py`:

```python
import pytest

@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && pytest tests/test_events.py::test_health -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Create `api/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    rate_limit_per_minute: int = 100

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 4: Create `api/main.py`**

```python
import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import settings
from routes import events


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await asyncpg.create_pool(settings.database_url)
    yield
    await app.state.db_pool.close()


app = FastAPI(lifespan=lifespan)

app.include_router(events.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def landing():
    return FileResponse("static/landing/index.html")


@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard/index.html")
```

- [ ] **Step 5: Create placeholder static files and routes package so the app loads**

Create `api/routes/__init__.py` (empty).

Create `api/static/landing/index.html`:
```html
<!DOCTYPE html><html><body><p>Landing page</p></body></html>
```

Create `api/static/dashboard/index.html`:
```html
<!DOCTYPE html><html><body><p>Dashboard</p></body></html>
```

- [ ] **Step 6: Run test to verify it passes**

```bash
cd api && pytest tests/test_events.py::test_health -v
```

Expected: `PASSED`

Note: this requires PostgreSQL running locally with a `fpcollector_test` database. Create it first:
```bash
psql -U fpcollector -c "CREATE DATABASE fpcollector_test;"
```

- [ ] **Step 7: Commit**

```bash
git add api/config.py api/main.py api/routes/__init__.py api/static/ api/tests/
git commit -m "feat: add FastAPI skeleton with health endpoint and test scaffold"
```

---

## Task 5: asyncpg database pool helper

**Files:**
- Create: `api/db.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_events.py`:

```python
@pytest.mark.asyncio
async def test_db_pool_is_available(client):
    from main import app
    assert app.state.db_pool is not None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && pytest tests/test_events.py::test_db_pool_is_available -v
```

Expected: `FAILED` — `AttributeError: db_pool` (pool not yet wired or not accessible via the test client)

The test client must share the app's lifespan. Update `conftest.py` — replace the `client` fixture:

```python
@pytest_asyncio.fixture
async def client():
    from main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        async with app.router.lifespan_context(app):
            yield c
```

- [ ] **Step 3: Run test to verify it now fails correctly**

```bash
cd api && pytest tests/test_events.py::test_db_pool_is_available -v
```

Expected: `PASSED` — `db_pool` is set by the lifespan.

- [ ] **Step 4: Create `api/db.py` as a thin accessor**

```python
from fastapi import Request
import asyncpg


def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.db_pool
```

- [ ] **Step 5: Commit**

```bash
git add api/db.py api/tests/conftest.py
git commit -m "feat: add db pool accessor and fix test client lifespan"
```

---

## Task 6: Pydantic event model

**Files:**
- Create: `api/models.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_events.py`:

```python
from models import EventRequest
import uuid
from datetime import datetime, timezone


def test_event_model_valid():
    data = {
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_abc",
        "anonymous_id": "anon_xyz",
        "page_url": "https://example.com",
        "consent_analytics": True,
        "payload": {},
    }
    event = EventRequest(**data)
    assert event.event_name == "page_view"


def test_event_model_rejects_invalid_event_name():
    import pytest
    from pydantic import ValidationError
    data = {
        "event_id": str(uuid.uuid4()),
        "event_name": "not_a_real_event",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_abc",
        "anonymous_id": "anon_xyz",
        "page_url": "https://example.com",
        "consent_analytics": True,
        "payload": {},
    }
    with pytest.raises(ValidationError):
        EventRequest(**data)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && pytest tests/test_events.py::test_event_model_valid tests/test_events.py::test_event_model_rejects_invalid_event_name -v
```

Expected: `FAILED` — `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Create `api/models.py`**

```python
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID
from pydantic import BaseModel


class EventRequest(BaseModel):
    event_id: UUID
    event_name: Literal["page_view", "cta_click", "form_submit"]
    occurred_at: datetime
    session_id: str
    anonymous_id: str
    page_url: str
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_term: Optional[str] = None
    utm_content: Optional[str] = None
    fbclid: Optional[str] = None
    consent_analytics: bool
    payload: dict = {}


class EventResponse(BaseModel):
    status: Literal["ok", "duplicate"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd api && pytest tests/test_events.py::test_event_model_valid tests/test_events.py::test_event_model_rejects_invalid_event_name -v
```

Expected: both `PASSED`

- [ ] **Step 5: Commit**

```bash
git add api/models.py
git commit -m "feat: add EventRequest Pydantic model with event_name enum validation"
```

---

## Task 7: Event ingest endpoint

**Files:**
- Create: `api/routes/events.py`

- [ ] **Step 1: Write the failing tests**

Add to `api/tests/test_events.py`:

```python
import uuid
from datetime import datetime, timezone


def make_event(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_test",
        "anonymous_id": "anon_test",
        "page_url": "https://example.com/",
        "consent_analytics": True,
        "payload": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ingest_valid_event(client):
    response = await client.post("/v1/events", json=make_event())
    assert response.status_code == 202
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ingest_duplicate_event(client):
    event = make_event()
    await client.post("/v1/events", json=event)
    response = await client.post("/v1/events", json=event)
    assert response.status_code == 202
    assert response.json() == {"status": "duplicate"}


@pytest.mark.asyncio
async def test_ingest_blocks_when_consent_false(client):
    response = await client.post("/v1/events", json=make_event(consent_analytics=False))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ingest_rejects_missing_required_field(client):
    event = make_event()
    del event["event_name"]
    response = await client.post("/v1/events", json=event)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_event_name(client):
    response = await client.post("/v1/events", json=make_event(event_name="bad_event"))
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd api && pytest tests/test_events.py -k "ingest" -v
```

Expected: all `FAILED` — `404 Not Found` (route does not exist yet)

- [ ] **Step 3: Create `api/routes/events.py`**

```python
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from asyncpg import Pool

from db import get_pool
from models import EventRequest, EventResponse

router = APIRouter()


@router.post("/v1/events", response_model=EventResponse, status_code=202)
async def ingest_event(event: EventRequest, request: Request, pool: Pool = Depends(get_pool)):
    if not event.consent_analytics:
        raise HTTPException(status_code=403, detail="consent required")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO raw_events (
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, referrer, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, fbclid, consent_analytics, payload
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15
            )
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
            """,
            event.event_id,
            event.event_name,
            event.occurred_at,
            event.session_id,
            event.anonymous_id,
            event.page_url,
            event.referrer,
            event.utm_source,
            event.utm_medium,
            event.utm_campaign,
            event.utm_term,
            event.utm_content,
            event.fbclid,
            event.consent_analytics,
            json.dumps(event.payload),
        )

    if row is None:
        return EventResponse(status="duplicate")
    return EventResponse(status="ok")
```

- [ ] **Step 4: Register the router in `api/main.py`**

The import is already present from Task 4. Verify `main.py` contains:
```python
from routes import events
# ...
app.include_router(events.router)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd api && pytest tests/test_events.py -k "ingest" -v
```

Expected: all 5 tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add api/routes/events.py api/main.py
git commit -m "feat: implement POST /v1/events with idempotency and consent gate"
```

---

## Task 8: Rate limiting

**Files:**
- Modify: `api/main.py`
- Modify: `api/routes/events.py`

- [ ] **Step 1: Write the failing test**

Add to `api/tests/test_events.py`:

```python
@pytest.mark.asyncio
async def test_rate_limit_applied(client):
    """Send 101 requests; the 101st must return 429."""
    event_base = make_event()
    for i in range(100):
        event = {**event_base, "event_id": str(uuid.uuid4())}
        r = await client.post("/v1/events", json=event)
        assert r.status_code == 202

    event = {**event_base, "event_id": str(uuid.uuid4())}
    r = await client.post("/v1/events", json=event)
    assert r.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd api && pytest tests/test_events.py::test_rate_limit_applied -v
```

Expected: `FAILED` — the 101st request returns `202` (no limiter yet)

- [ ] **Step 3: Create `api/limiter.py` (shared Limiter instance)**

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
```

slowapi requires the same `Limiter` instance to be used both in `app.state.limiter` and in `@limiter.limit()` decorators. This module is the single source of truth.

- [ ] **Step 4: Update `api/main.py` to use the shared limiter**

Replace the contents of `api/main.py` with:

```python
import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from config import settings
from limiter import limiter
from routes import events


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await asyncpg.create_pool(settings.database_url)
    yield
    await app.state.db_pool.close()


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(events.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def landing():
    return FileResponse("static/landing/index.html")


@app.get("/dashboard")
async def dashboard():
    return FileResponse("static/dashboard/index.html")
```

- [ ] **Step 5: Update `api/routes/events.py` to import the shared limiter**

Replace the contents of `api/routes/events.py` with:

```python
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from asyncpg import Pool

from db import get_pool
from limiter import limiter
from models import EventRequest, EventResponse

router = APIRouter()


@router.post("/v1/events", response_model=EventResponse, status_code=202)
@limiter.limit("100/minute")
async def ingest_event(request: Request, event: EventRequest, pool: Pool = Depends(get_pool)):
    if not event.consent_analytics:
        raise HTTPException(status_code=403, detail="consent required")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO raw_events (
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, referrer, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, fbclid, consent_analytics, payload
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15
            )
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
            """,
            event.event_id,
            event.event_name,
            event.occurred_at,
            event.session_id,
            event.anonymous_id,
            event.page_url,
            event.referrer,
            event.utm_source,
            event.utm_medium,
            event.utm_campaign,
            event.utm_term,
            event.utm_content,
            event.fbclid,
            event.consent_analytics,
            json.dumps(event.payload),
        )

    if row is None:
        return EventResponse(status="duplicate")
    return EventResponse(status="ok")
```

Note: slowapi requires `request: Request` as the **first** parameter of the route function.

- [ ] **Step 5: Run all tests**

```bash
cd api && pytest tests/ -v
```

Expected: all tests `PASSED` including `test_rate_limit_applied`

- [ ] **Step 6: Commit**

```bash
git add api/main.py api/routes/events.py
git commit -m "feat: add per-IP rate limiting via slowapi (100 req/min)"
```

---

## Task 9: Landing page + client tracking script

**Files:**
- Modify: `api/static/landing/index.html`
- Create: `api/static/landing/tracker.js`

This task has no automated tests — verify by opening the page in a browser and checking the Network tab for event requests.

- [ ] **Step 1: Create `api/static/landing/tracker.js`**

```javascript
(function () {
  const COLLECTOR_URL = '/v1/events';
  const CONSENT_KEY = 'consent_analytics';
  const ANON_KEY = 'anonymous_id';

  function getOrCreate(storage, key, factory) {
    let val = storage.getItem(key);
    if (!val) { val = factory(); storage.setItem(key, val); }
    return val;
  }

  function uuidv4() {
    return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
      (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
    );
  }

  const anonymousId = getOrCreate(localStorage, ANON_KEY, uuidv4);
  const sessionId   = getOrCreate(sessionStorage, 'session_id', uuidv4);

  function getUtmParams() {
    const p = new URLSearchParams(window.location.search);
    return {
      utm_source:   p.get('utm_source')   || null,
      utm_medium:   p.get('utm_medium')   || null,
      utm_campaign: p.get('utm_campaign') || null,
      utm_term:     p.get('utm_term')     || null,
      utm_content:  p.get('utm_content')  || null,
      fbclid:       p.get('fbclid')       || null,
    };
  }

  function hasConsent() {
    return localStorage.getItem(CONSENT_KEY) === 'true';
  }

  window.track = function (eventName, payload = {}) {
    if (!hasConsent()) return;
    fetch(COLLECTOR_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event_id:          uuidv4(),
        event_name:        eventName,
        occurred_at:       new Date().toISOString(),
        session_id:        sessionId,
        anonymous_id:      anonymousId,
        page_url:          window.location.href,
        referrer:          document.referrer || null,
        consent_analytics: true,
        payload:           payload,
        ...getUtmParams(),
      }),
    }).catch(() => {});
  };

  window.grantConsent = function () {
    localStorage.setItem(CONSENT_KEY, 'true');
    track('page_view');
  };

  if (hasConsent()) {
    track('page_view');
  }
})();
```

- [ ] **Step 2: Create `api/static/landing/index.html`**

```html
<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>fp-collector demo</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f5f5f5; color: #111; }
    .hero { max-width: 720px; margin: 80px auto; text-align: center; padding: 0 24px; }
    h1 { font-size: 2.5rem; margin-bottom: 16px; }
    p  { font-size: 1.1rem; color: #555; margin-bottom: 32px; }
    .cta { display: inline-block; background: #2563eb; color: #fff;
           padding: 14px 32px; border-radius: 8px; font-size: 1rem;
           cursor: pointer; border: none; text-decoration: none; }
    .cta:hover { background: #1d4ed8; }
    .consent-banner { position: fixed; bottom: 0; left: 0; right: 0;
                      background: #1e1e1e; color: #fff; padding: 16px 24px;
                      display: flex; align-items: center; gap: 16px;
                      font-size: 0.9rem; }
    .consent-banner button { background: #2563eb; color: #fff; border: none;
                             padding: 8px 20px; border-radius: 6px; cursor: pointer; }
    #banner { display: none; }
  </style>
</head>
<body>
  <div class="hero">
    <h1>First-Party Data Demo</h1>
    <p>Saját collector, saját pipeline — teljes kontroll az adatok felett.</p>
    <button class="cta" id="cta-btn" onclick="track('cta_click', {label: 'hero_cta'})">
      Érdekel, tudj meg többet
    </button>
  </div>

  <div id="banner" class="consent-banner">
    <span>Ez az oldal saját analytics rendszert használ a felhasználói interakciók mérésére.</span>
    <button onclick="grantConsent(); document.getElementById('banner').style.display='none'">
      Elfogadom
    </button>
  </div>

  <script src="/static/landing/tracker.js"></script>
  <script>
    if (!localStorage.getItem('consent_analytics')) {
      document.getElementById('banner').style.display = 'flex';
    }
  </script>
</body>
</html>
```

- [ ] **Step 3: Verify manually**

```bash
cd api && uvicorn main:app --reload
```

Open `http://localhost:8000` in a browser. Expected:
1. Consent banner appears on first visit.
2. After clicking "Elfogadom": banner disappears, a `page_view` event appears in the Network tab as `POST /v1/events` returning `202`.
3. Clicking the CTA button sends a `cta_click` event.
4. On page reload, `page_view` fires immediately (no banner — consent is remembered).

- [ ] **Step 4: Commit**

```bash
git add api/static/landing/
git commit -m "feat: add landing page with consent banner and tracker.js"
```

---

## Task 10: Docker build + smoke test

- [ ] **Step 1: Build and start the stack**

```bash
docker compose up --build -d
```

- [ ] **Step 2: Check service health**

```bash
docker compose ps
```

Expected: both `api` and `db` show status `running (healthy)` or `running`.

- [ ] **Step 3: Smoke test the API**

```bash
curl -s -X POST http://localhost:8000/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "00000000-0000-0000-0000-000000000001",
    "event_name": "page_view",
    "occurred_at": "2026-04-21T12:00:00Z",
    "session_id": "smoke-session",
    "anonymous_id": "smoke-anon",
    "page_url": "https://example.com/",
    "consent_analytics": true,
    "payload": {}
  }'
```

Expected: `{"status":"ok"}`

- [ ] **Step 4: Send the same event again (idempotency check)**

```bash
curl -s -X POST http://localhost:8000/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "00000000-0000-0000-0000-000000000001",
    "event_name": "page_view",
    "occurred_at": "2026-04-21T12:00:00Z",
    "session_id": "smoke-session",
    "anonymous_id": "smoke-anon",
    "page_url": "https://example.com/",
    "consent_analytics": true,
    "payload": {}
  }'
```

Expected: `{"status":"duplicate"}`

- [ ] **Step 5: Verify row exists in DB**

```bash
docker compose exec db psql -U fpcollector -d fpcollector -c "SELECT event_id, event_name, received_at FROM raw_events;"
```

Expected: one row with `event_id = 00000000-...0001`.

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "chore: Phase 1 complete — collector API deployable and smoke-tested"
```

---

## pytest configuration

Create `api/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

Add this commit before running any tests:

```bash
git add api/pytest.ini
git commit -m "chore: add pytest config for asyncio_mode=auto"
```

---

## Test database setup (prerequisite for Tasks 4–8)

Before running tests, the `fpcollector_test` database must exist. Run once:

```bash
docker compose up -d db
docker compose exec db psql -U fpcollector -c "CREATE DATABASE fpcollector_test;"
```

Then install Python dependencies locally for test runs:

```bash
cd api && pip install -r requirements.txt
```

Set the test DATABASE_URL (the conftest.py sets it via `os.environ.setdefault`, so no extra config needed if the default value matches your local DB).
