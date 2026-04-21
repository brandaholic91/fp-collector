# fp-collector — Technical Design

**Date:** 2026-04-21
**Status:** Approved

## 1. Scope

This document covers the technical decisions for Phase 1–3 of the fp-collector project: the Event Collector API, PostgreSQL storage, client tracking script, and custom dashboard — all running as a single FastAPI application deployed on `dokploy-lab`.

## 2. Tech Stack

| Layer | Technology |
|---|---|
| API + server | Python 3.12 + FastAPI |
| Database driver | asyncpg (async PostgreSQL) |
| Input validation | Pydantic v2 (FastAPI built-in) |
| Rate limiting | slowapi (in-memory, per IP) |
| Database | PostgreSQL 16.3 |
| Frontend | Vanilla HTML/CSS/JS |
| Container | Docker + Docker Compose |
| Reverse proxy | Nginx Proxy Manager (existing, dokploy-lab) |

Database access uses raw SQL via asyncpg — no ORM. The project has 3 tables and a small set of queries; ORM complexity is not justified.

## 3. Architecture

One Docker Compose stack with two services: `api` and `db`.

```
┌─────────────────────────────────────┐
│           fp-collector              │
│                                     │
│  FastAPI app                        │
│  ├── POST /v1/events   (ingest)     │
│  ├── GET  /api/stats/* (dashboard)  │
│  ├── /                (landing)     │
│  └── /dashboard       (dashboard)   │
│                                     │
│  static/                            │
│  ├── landing/index.html             │
│  ├── landing/tracker.js             │
│  └── dashboard/index.html           │
└──────────────┬──────────────────────┘
               │ asyncpg
┌──────────────▼──────────────────────┐
│         PostgreSQL 16.3             │
│  raw_events / clean_events / leads  │
└─────────────────────────────────────┘
```

The `api` service joins both `internal` (bridge) and `proxy-net` (external) networks. The `db` service is on `internal` only — never exposed outside the stack.

Static files (landing page, dashboard) are served via FastAPI `StaticFiles` mount. No server-side rendering; the dashboard fetches data from `/api/stats/*` endpoints via JavaScript.

## 4. Project Structure

```
fp-collector/
├── docker-compose.yml
├── .env.example
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py              # FastAPI app, route registration, lifespan
│   ├── config.py            # env var loading (pydantic-settings)
│   ├── db.py                # asyncpg connection pool (init/teardown)
│   ├── models.py            # Pydantic request/response models
│   ├── routes/
│   │   ├── events.py        # POST /v1/events
│   │   └── stats.py         # GET /api/stats/*
│   └── static/
│       ├── landing/
│       │   ├── index.html
│       │   └── tracker.js
│       └── dashboard/
│           └── index.html
├── db/
│   └── init.sql             # CREATE TABLE statements, run on first start
└── docs/
```

## 5. Database Schema

```sql
CREATE TABLE raw_events (
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

CREATE INDEX idx_raw_events_occurred_at ON raw_events (occurred_at);
CREATE INDEX idx_raw_events_event_name  ON raw_events (event_name);
CREATE INDEX idx_raw_events_session_id  ON raw_events (session_id);

CREATE TABLE clean_events (
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

CREATE TABLE leads (
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

Notes:
- `fbclid` is nullable on `raw_events` — reserved for planned Meta CAPI integration.
- `source_medium` on `clean_events` is populated by n8n (e.g. `"google / cpc"`).
- Schema is applied via `db/init.sql` mounted into the PostgreSQL container at `docker-entrypoint-initdb.d/`.

## 6. API Contract

### POST /v1/events

**Request body:**

```json
{
  "event_id": "uuid",
  "event_name": "page_view | cta_click | form_submit",
  "occurred_at": "2026-04-21T10:00:00Z",
  "session_id": "string",
  "anonymous_id": "string",
  "page_url": "string",
  "referrer": "string | null",
  "utm_source": "string | null",
  "utm_medium": "string | null",
  "utm_campaign": "string | null",
  "utm_term": "string | null",
  "utm_content": "string | null",
  "fbclid": "string | null",
  "consent_analytics": true,
  "payload": {}
}
```

**Response codes:**

| Situation | HTTP | Body |
|---|---|---|
| Successful ingest | 202 | `{"status": "ok"}` |
| Duplicate event_id | 202 | `{"status": "duplicate"}` |
| consent_analytics false | 403 | `{"detail": "consent required"}` |
| Validation error | 422 | FastAPI default |
| Rate limit exceeded | 429 | slowapi default |

Idempotency: implemented via `INSERT ... ON CONFLICT (event_id) DO NOTHING`. The API returns `202` in both the new and duplicate cases to avoid leaking state to the client.

### GET /api/stats/funnel

Returns aggregate counts for `page_view → cta_click → form_submit` funnel steps.

### GET /api/stats/events

Returns daily event counts grouped by `event_name` for time-series charts.

### GET /api/stats/utm

Returns event counts grouped by `utm_source` and `utm_medium`.

Response schemas for stats endpoints are defined during Phase 3 (dashboard implementation), driven by the actual chart requirements.

**Rate limiting:** 100 requests/minute per IP, in-memory via slowapi. Sufficient for homelab/portfolio load without requiring Redis.

## 7. Docker & Deployment

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

**`.env.example`:**

```env
POSTGRES_USER=fpcollector
POSTGRES_PASSWORD=changeme
POSTGRES_DB=fpcollector
DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector
RATE_LIMIT_PER_MINUTE=100
```

Docker rules applied: `proxy-net` external network, `expose` (not `ports`), fixed image tags, secrets in `.env` only.

Deploy path on server: `/mnt/data/stacks/fp-collector/`. File ownership: `balazs:balazs`.

## 8. Client Tracking Script

`tracker.js` is a vanilla JS module loaded on the landing page. Responsibilities:

- Generate and persist `anonymous_id` in `localStorage` (UUID, set once).
- Generate `session_id` per browser session (`sessionStorage`).
- Read UTM parameters from the current URL on page load.
- Expose a `track(eventName, payload)` function.
- Fire `page_view` automatically on load.
- Fire `cta_click` and `form_submit` on user interaction (called manually from the page).
- Gate all tracking behind `consent_analytics: true` (checked before every send). Consent is signalled by a simple in-page banner that sets a `consent_analytics=true` flag in `localStorage`; the flag is read before each `track()` call.
- Send events via `fetch` to `POST /v1/events` with the full required schema.

## 9. Open Decisions

These items are intentionally deferred to Phase 3:

- Exact response schema for `/api/stats/*` endpoints.
- Dashboard layout and KPI visualisation details.
- Landing page copy and design.
