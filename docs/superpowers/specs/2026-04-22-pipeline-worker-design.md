# Pipeline Worker Design

**Date:** 2026-04-22
**Status:** Approved

## Context

The n8n-based pipeline (raw_events → clean_events → leads) is replaced by a self-hosted Python worker running inside the existing `fp-collector-api` Docker image. This eliminates the external n8n dependency and the parameter-binding issues that caused silent processing failures.

## Architecture

The worker runs as a separate container from the same image as the API, sharing the codebase and configuration. It polls `raw_events` every 10 seconds and processes unhandled rows through the full pipeline.

```
raw_events (processed_at IS NULL)
    └── worker.py (poll every 10s)
            ├── compute source_medium
            ├── INSERT clean_events
            ├── INSERT leads (form_submit only)
            └── UPDATE raw_events.processed_at
```

## Components

| File | Purpose |
|------|---------|
| `api/worker.py` | Poll loop + pipeline logic |
| `docker-compose.yml` | New `worker` service with `command: python worker.py` |

## Pipeline Logic

1. **Fetch batch** — `SELECT ... FROM raw_events WHERE processed_at IS NULL AND processing_error IS NULL ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`
2. **Compute source_medium** — UTM params take priority; fallback to referrer hostname classification (google/facebook/linkedin/twitter/referral); default to `direct / none`
3. **INSERT clean_events** — `ON CONFLICT (event_id) DO NOTHING`; duplicate counts as success
4. **INSERT leads** — only for `event_name = 'form_submit'`; same transaction as clean_events insert
5. **Mark processed** — `UPDATE raw_events SET processed_at = now() WHERE id = $1`

## Error Handling

- Each `raw_event` is processed in its own transaction.
- On failure: `processing_error = <error message>`, `processed_at` left NULL. The row is skipped on subsequent runs until manually cleared.
- DB connection loss: worker exits; Docker `restart: unless-stopped` brings it back. No data loss since `processed_at` remains NULL.
- No automatic retry — failed rows require manual intervention or a future dead-letter sweep.

## Docker Configuration

New service in `docker-compose.yml`:

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

No `proxy-net` — the worker accepts no public traffic.

## Configuration

No new env vars required. Optional: `WORKER_POLL_INTERVAL=10` (seconds) to make the poll interval configurable via `.env`.

## Success Criteria

- All `raw_events` with `processed_at IS NULL` are processed within p95 < 60s
- Failed rows have a non-null `processing_error` and are never silently dropped
- Worker survives DB restarts via Docker restart policy
- No dependency on n8n for pipeline processing
