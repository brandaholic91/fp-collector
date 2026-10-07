# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**fp-collector** is an end-to-end first-party data collection and processing system. It is a MarTech portfolio project built as a reference implementation for collecting structured web analytics events through a self-hosted pipeline.

**Data flow:** Browser → Client tracking script → Event Collector API → PostgreSQL (`raw_events`) → Python worker → `clean_events`/`leads` → Dashboard

## Stack Architecture

| Component | Role | Target Lab |
|---|---|---|
| Landing page + client tracking script | User-facing frontend, fires events | `dokploy-lab` |
| Event Collector API (`POST /v1/events`) | Receives, validates, idempotently stores events | `dokploy-lab` |
| PostgreSQL | Two-layer storage: `raw_events`, `clean_events`, `leads` | `dokploy-lab` |
| Python worker (`api/worker.py`) | Dedup, enrichment, normalization, lead creation | `dokploy-lab` |
| Dashboard | KPI and funnel visualization | `dokploy-lab` |
| Umami (Phase 4) | Secondary analytics validation layer | `dokploy-lab` |

## Event Schema

Every event sent to `POST /v1/events` must include:

```json
{
  "event_id": "<UUID, client-generated>",
  "event_name": "page_view | cta_click | form_submit",
  "occurred_at": "<ISO 8601 timestamp>",
  "session_id": "<string>",
  "anonymous_id": "<cookie/localStorage UUID>",
  "page_url": "<string>",
  "referrer": "<string>",
  "utm_source": "<string>",
  "utm_medium": "<string>",
  "utm_campaign": "<string>",
  "utm_term": "<string>",
  "utm_content": "<string>",
  "consent_analytics": true,
  "payload": {}
}
```

**Idempotency:** `event_id` is the deduplication key. The API must reject or ignore duplicate `event_id` values (upsert-ignore pattern on `raw_events`).

**E-commerce events** (`view_item`, `add_to_cart`, `begin_checkout`, `purchase`) are accepted
only when `ECOMMERCE_ENABLED=true`; otherwise they are rejected with 422 like any unknown name.
A `purchase` must carry `order_id`, a positive `value`, `currency` and `customer_key` in
`payload`.

## Database Layers

- `raw_events` — ingested as-is with minimal transformation; source of truth.
- `clean_events` — validated, normalized, deduplicated by the worker.
- `leads` — created from `form_submit` events by the worker.

## API Rules

- Input validation is strict (reject on missing required fields or invalid schema).
- Rate limiting must be applied at the API level.
- Events with `consent_analytics: false` must be blocked before storage.
- Never expose the database port directly; API is the only ingress.

## Deployment Target (homelab)

Production runs on `dokploy-lab` inside the Proxmox MarTech homelab.

**Stack path on server:**
```
/mnt/data/stacks/fp-collector/
├── docker-compose.yml
└── data/
```

**Docker rules (non-negotiable):**
- All public services must join the `proxy-net` external network.
- Use `expose:` instead of `ports:` — ingress via Nginx Proxy Manager only.
- Always use fixed image tags or SHA256 digests. Never `:latest`.
- File ownership under `/mnt/data/stacks` must be `balazs:balazs`.
- Secrets go in `.env` files, never in `docker-compose.yml` or committed to the repo.

**Internal DNS:** Services are accessed via `*.home.arpa` (managed by CoreDNS + NPM).

## Privacy & Consent

- Events may only be ingested after `consent_analytics: true` is confirmed client-side.
- Backend must also validate consent before writing to the database.
- No PII should be stored without explicit schema design decision.

## KPIs to Track

- Event ingest success rate (target: ≥ 98%)
- Duplicate event rate (target: ≤ 1%)
- Landing → CTA conversion rate
- CTA → Lead conversion rate
- Overall funnel conversion rate
- Lead volume by UTM source/medium

## Worker Pipeline Expectations

- Trigger: the worker polls `raw_events` for unprocessed rows every `WORKER_POLL_INTERVAL` seconds.
- Outputs: enriched rows in `clean_events` (with a derived `source_medium`); lead rows in `leads`.
- p95 processing latency target: < 60s.
- Failed records are never silently dropped: the error is written to `raw_events.processing_error`
  and the row is not retried.

## World instance (synthetic webshop traffic)

A second, **local and disposable** instance of this stack receives the synthetic traffic of the
portfolio's fictional webshop (`~/Projects/portfolio-holikbalazs/world`). It has its own compose
project, volume and ports, and never shares a database with production.

```bash
cp .env.world.example .env.world                               # once
docker compose -f docker-compose.world.yml up -d --build --wait
curl -s http://127.0.0.1:18080/health                          # {"status":"ok"}
docker compose -f docker-compose.world.yml down                # stop, keep the data
docker compose -f docker-compose.world.yml down -v             # stop and wipe the data
```

API on `127.0.0.1:18080`, Postgres on `127.0.0.1:15433`.

Two settings exist for this instance. Both default to `false`, so production is unaffected:

| Setting | Effect when `true` |
|---|---|
| `ECOMMERCE_ENABLED` | accepts the four e-commerce events; enables `POST /v1/events/batch` (1-1000 events per request, no rate limit); a `purchase` also writes `orders` and `identity_links` |
| `WORKER_BATCHED` | the worker processes 5000 rows per transaction with set-based SQL, falling back to per-event processing if the batch fails |

`resolved_events` is a view over `clean_events` that adds `person_id`: the linked `customer_key`
if the device has ever purchased, otherwise the `anonymous_id` itself.

**Synthetic traffic must never reach the production database.** Production does not need
`db/migrations/004_ecommerce.sql`: with the flag off no `purchase` can reach the worker.

## Running the tests locally

```bash
docker run -d --name fp-test-db \
  -e POSTGRES_USER=fpcollector -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=fpcollector_test \
  -p 127.0.0.1:25432:5432 \
  -v "$PWD/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" postgres:16.3
cd api && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
DATABASE_URL=postgresql://fpcollector:changeme@localhost:25432/fpcollector_test \
  .venv/bin/python -m pytest -q --deselect tests/test_phase2_permissions.py
```

`test_phase2_permissions.py` needs the `n8n_worker` role and the `db` hostname; it only runs
inside the compose network. After changing `db/init.sql`, re-apply it to the test database:
`docker exec -i fp-test-db psql -q -U fpcollector -d fpcollector_test < db/init.sql`.

## Development Phases

1. **Phase 0** — Schema, KPI definitions, runbook skeleton
2. **Phase 1** — Collector API MVP + PostgreSQL + client tracking script
3. **Phase 2** — Worker dedup/enrichment pipeline
4. **Phase 3** — Dashboard and funnel reporting
5. **Phase 4** — Umami integration (secondary validation)
6. **Phase 5** — Portfolio packaging (README, diagrams, runbook)
