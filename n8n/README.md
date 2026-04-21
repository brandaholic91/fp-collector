# n8n Workflow — fp-collector-pipeline

## Purpose

Processes rows from `raw_events`, enriches them with a derived `source_medium`, writes normalized rows to `clean_events`, and creates `leads` rows from `form_submit` events.

- Trigger: Schedule, every 30 seconds
- Batch size: 100 rows (LIMIT in the polling query)
- Latency target: p95 < 60s

## Import

1. Open n8n → **Workflows** → **Import from File** → select `n8n/workflows/fp-collector-pipeline.json`.
2. Create a PostgreSQL credential named `fp-collector-n8n-worker`:
   - **Host:** dokploy-lab LAN IP (e.g. `192.168.1.50`) or Docker network hostname if n8n shares a network with the DB
   - **Port:** `5432`
   - **Database:** `fpcollector`
   - **User:** `n8n_worker`
   - **Password:** value of `N8N_WORKER_PASSWORD` from the dokploy-lab `.env`
3. Assign the credential to every PostgreSQL node in the workflow (Fetch, Insert clean_events, Insert lead, Mark as processed, Set processing_error).
4. Activate the workflow.

## Attribution Rules (source_medium)

The `Compute source_medium` Code node derives `source_medium` for each event using this priority:

1. **UTM present** — `utm_source / utm_medium` (lowercased).
2. **fbclid present (no UTM)** — `facebook / cpc`.
3. **Referrer present** — mapped from hostname:
   - `google.*` → `google / organic`
   - `facebook.*`, `instagram.*` → `facebook / referral`
   - `linkedin.*` → `linkedin / referral`
   - `twitter.*`, `t.co`, `x.com` → `twitter / referral`
   - anything else → `<hostname> / referral`
4. **None of the above** — `direct / none`.

## MVP Simplifications

- No `gclid` handling — UTMs cover Google Ads in practice.
- `google / organic` vs `google / cpc` relies on UTM tagging.
- Referrer categorization uses simple substring matching.
- No lead deduplication; each `form_submit` creates a new `leads` row.

## Implementation Notes

- **Query batching: Independent** — the Insert clean_events and Insert lead nodes must run one query per item. Without this, n8n collapses all items into a single batched query and the single `{success: true}` output item loses per-row context.
- **`$('Fetch unprocessed batch').item.json.*` in downstream nodes** — the Postgres node output after an INSERT is `{success: true}`. Downstream nodes (IF, Mark as processed, Insert lead, Set processing_error) reach back to the original source row via the pairedItem lookup on the Fetch node.
- **Error routing** — Insert clean_events and Insert lead nodes have `On Error: Continue (using error output)`. Their error outputs feed `Set processing_error`, which flags the failed row in `raw_events.processing_error` without breaking the rest of the batch.
- **Concurrency** — `FOR UPDATE SKIP LOCKED` in the polling query prevents double-processing under overlapping schedule firings.

## Operations

**Retry failed rows:**

```sql
UPDATE raw_events SET processing_error = NULL WHERE processing_error LIKE '%pattern%';
```

**Full backfill:**

```sql
UPDATE raw_events SET processed_at = NULL, processing_error = NULL;
```

`ON CONFLICT (event_id) DO NOTHING` on `clean_events` makes re-processing idempotent.

**Monitoring:**

- n8n execution history shows failed runs.
- Dead-letter rows: `SELECT * FROM raw_events WHERE processing_error IS NOT NULL`.

## Smoke Test

To validate end-to-end processing:

```bash
docker-compose exec \
  -e DATABASE_URL=postgresql://fpcollector:changeme@db:5432/fpcollector \
  -e PHASE2_SMOKE=1 \
  api python -m pytest tests/test_phase2_smoke.py -v -s
```

Seeds 3 events, waits 45s for the workflow to process them, asserts all reach the expected target tables with correct source_medium values.
