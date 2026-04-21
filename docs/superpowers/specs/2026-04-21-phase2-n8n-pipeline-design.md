# fp-collector Phase 2 — n8n Pipeline Technical Design

**Date:** 2026-04-21
**Status:** Approved

## 1. Scope

This document covers the Phase 2 pipeline: an n8n workflow that polls new rows in `raw_events`, enriches them with a derived `source_medium`, writes them to `clean_events`, creates `leads` rows from `form_submit` events, and handles failures via a dead-letter pattern.

High-value lead alerting (Slack/Discord webhook) is intentionally deferred until a lead scoring mechanism exists. It is not part of Phase 2.

## 2. Architecture

A single n8n workflow running on the existing `martech-lab` n8n instance. The workflow polls the `fp-collector` PostgreSQL (on `dokploy-lab`) every 30 seconds in batches of up to 100 rows.

```
[Schedule: 30s]
    ↓
[PG SELECT: unprocessed batch (LIMIT 100, FOR UPDATE SKIP LOCKED)]
    ↓
[IF rows > 0] ────── false ──→ END
    ↓ true
[Code node: compute source_medium for each row]
    ↓
[PG INSERT clean_events] ──── on error ──→ [PG UPDATE processing_error]
    ↓
[IF any form_submit]
    ↓ true
[PG INSERT leads from form_submits]
    ↓
[PG UPDATE raw_events SET processed_at = now()]
    ↓
END
```

**Key design decisions:**

- **Polling over webhook push** — decouples n8n from the API, survives n8n downtime, meets the p95 < 60s latency target comfortably.
- **Single workflow, not multiple** — the pipeline is linear; splitting into separate workflows would fragment related logic unnecessarily.
- **Batch SQL over per-row loops** — one `INSERT INTO clean_events` per batch is orders of magnitude cheaper than 100 individual inserts.
- **Direct PostgreSQL access with restricted user** — n8n is a trusted internal service on the homelab LAN; adding API endpoints to avoid DB access would add complexity without security benefit.

## 3. Database Schema Changes

### 3.1 Migration: processing state columns

New file: `db/migrations/002_add_processing_state.sql`

```sql
ALTER TABLE raw_events
    ADD COLUMN IF NOT EXISTS processed_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_error TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed
    ON raw_events (id)
    WHERE processed_at IS NULL AND processing_error IS NULL;
```

The partial index keeps the polling query fast regardless of table size — only unprocessed rows are indexed.

### 3.2 Update `db/init.sql`

The canonical schema in `db/init.sql` is updated to include `processed_at` and `processing_error` on `raw_events` plus the partial index, so fresh deployments get the complete schema without needing to run migrations.

### 3.3 Migration: n8n_worker user

New file: `db/migrations/003_create_n8n_worker_user.sql`

```sql
CREATE USER n8n_worker WITH PASSWORD :'n8n_worker_password';

GRANT CONNECT ON DATABASE fpcollector TO n8n_worker;
GRANT USAGE ON SCHEMA public TO n8n_worker;

GRANT SELECT, UPDATE (processed_at, processing_error) ON raw_events TO n8n_worker;
GRANT INSERT ON clean_events TO n8n_worker;
GRANT INSERT ON leads TO n8n_worker;

GRANT USAGE, SELECT ON SEQUENCE clean_events_id_seq TO n8n_worker;
GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO n8n_worker;
```

**Principle of least privilege:** `n8n_worker` can only update two specific columns on `raw_events` and cannot alter the original ingested data. The `fpcollector` superuser remains used only by the API.

The password is supplied via psql variable (`-v n8n_worker_password='...'`) at migration time and stored in `.env` on the dokploy-lab server (not committed).

## 4. source_medium Derivation (Code Node)

The workflow's Code node runs this JavaScript on each batch item:

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

**Attribution priority:**

1. UTM parameters present → `utm_source / utm_medium` (lowercased)
2. `fbclid` present (no UTM) → `facebook / cpc`
3. Referrer present → mapped by domain
4. Otherwise → `direct / none`

**Documented simplifications** (to go in `n8n/README.md`):

- No `gclid` handling (Google Ads click id) — UTMs cover this case in practice.
- `google / organic` vs `google / cpc` distinction relies on UTM tagging, not on search-vs-ads detection.
- Referrer parsing uses simple substring matching, not a maintained referrer database.

These simplifications are MVP scope; extending attribution logic is a future iteration.

## 5. n8n Workflow Nodes

### 5.1 Schedule Trigger

- Type: Schedule Trigger
- Interval: `every 30 seconds`

### 5.2 PostgreSQL — Fetch unprocessed batch

```sql
SELECT id, event_id, event_name, occurred_at, session_id, anonymous_id,
       page_url, referrer, utm_source, utm_medium, utm_campaign,
       utm_term, utm_content, fbclid, payload
FROM raw_events
WHERE processed_at IS NULL AND processing_error IS NULL
ORDER BY id
LIMIT 100
FOR UPDATE SKIP LOCKED;
```

`FOR UPDATE SKIP LOCKED` guards against double-processing if the schedule fires while a previous execution is still running, or if someone triggers the workflow manually.

### 5.3 IF — Has rows?

Expression: `{{ $items().length > 0 }}`. False branch ends the workflow.

### 5.4 Code — Compute source_medium

JavaScript from Section 4.

### 5.5 PostgreSQL — Insert clean_events

```sql
INSERT INTO clean_events (
    raw_event_id, event_id, event_name, occurred_at, session_id, anonymous_id,
    page_url, referrer, utm_source, utm_medium, utm_campaign, source_medium, payload
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (event_id) DO NOTHING;
```

Executed once per item. `ON CONFLICT DO NOTHING` protects against a retry scenario where a row is partially processed.

### 5.6 IF — Is form_submit?

Expression: `{{ $json.event_name === 'form_submit' }}`.

### 5.7 PostgreSQL — Insert leads

```sql
INSERT INTO leads (event_id, anonymous_id, occurred_at, utm_source, utm_medium, utm_campaign, payload)
VALUES ($1, $2, $3, $4, $5, $6, $7);
```

No dedup on `leads`: each `form_submit` creates a new row. Dedup (by email, anonymous_id, etc.) is intentionally out of scope and can be added later if a lead-scoring layer introduces such rules.

### 5.8 PostgreSQL — Mark as processed

```sql
UPDATE raw_events SET processed_at = now() WHERE id = ANY($1);
```

`$1` is an array of `id` values collected from the batch.

### 5.9 Error handler branch

Implementation detail to be finalized in n8n during the build: each PG node has "On Error: Continue with error output" configured, routing failed items into:

```sql
UPDATE raw_events SET processing_error = $2 WHERE id = $1;
```

A failed batch does not block the next scheduled execution — the failed rows are skipped via `processing_error IS NOT NULL` in the polling query.

## 6. Docker Compose Update

The `db` service needs to be reachable from `martech-lab`'s n8n. Two approaches — the final choice is made at implementation time based on the existing homelab network topology:

**Option X: Shared external Docker network (`homelab-internal`)**

```yaml
services:
  db:
    # ... existing config ...
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

Used if the two Proxmox LXCs already share a Docker network (or if we set one up).

**Option Y: Bind PostgreSQL to the dokploy-lab LAN IP**

Add `ports: - "10.10.10.20:5432:5432"` to the db service (with the LAN IP, not `0.0.0.0`). n8n connects using that IP.

This is what we do if there is no shared Docker network. It does not expose the DB publicly because it binds only to the internal LAN IP.

The selection is documented in the implementation plan once current network topology is verified.

## 7. Repository Structure

```
fp-collector/
├── api/                                # Phase 1 — unchanged
├── db/
│   ├── init.sql                        # updated: raw_events + processing cols
│   └── migrations/
│       ├── 002_add_processing_state.sql
│       └── 003_create_n8n_worker_user.sql
├── n8n/
│   ├── workflows/
│   │   └── fp-collector-pipeline.json  # exported n8n workflow
│   └── README.md                       # import guide + attribution rules
├── docker-compose.yml                  # updated: homelab-internal network OR LAN IP binding
└── docs/superpowers/
    ├── specs/2026-04-21-phase2-n8n-pipeline-design.md
    └── plans/2026-04-21-phase2-n8n-pipeline.md     # next step
```

The workflow JSON is committed to the repo so the pipeline is reproducible. The JSON references credentials by name only — real secrets stay in n8n's credential store.

## 8. Operational Concerns

**Monitoring:** n8n's execution history is the primary observability tool. Failed executions show up in the UI; a manual check or a future alerting workflow can surface them.

**Retry:** operator clears the error by running
```sql
UPDATE raw_events SET processing_error = NULL WHERE processing_error LIKE '%some pattern%';
```
The next poll picks these rows up again.

**Backfill:** to reprocess all rows, set `processed_at = NULL` and `processing_error = NULL`. `ON CONFLICT DO NOTHING` in the `clean_events` insert keeps the operation idempotent.

**Concurrency:** `FOR UPDATE SKIP LOCKED` in the polling query plus the `ON CONFLICT` on `clean_events.event_id` guarantee no duplicate clean rows even under overlapping executions.

## 9. Success Criteria

- p95 processing latency (raw_events row inserted → clean_events row inserted) < 60s.
- Every `form_submit` in `clean_events` has a matching row in `leads`.
- Failed rows are visible via `SELECT ... WHERE processing_error IS NOT NULL` and do not block the pipeline.
- Workflow JSON is reproducible: a fresh n8n instance can import it and run after credentials are set.

## 10. Deferred / Out of Scope

- **High-value lead webhook alerting** — needs a lead-scoring layer first.
- **gclid handling** and richer attribution rules (see Section 4 simplifications).
- **Automated migration tooling** — migrations are applied manually via psql on dokploy-lab (documented in the plan).
- **Lead deduplication** — each `form_submit` creates a new `leads` row; deduplication requires business rules (by email? by anonymous_id + form?) that are not yet defined.
