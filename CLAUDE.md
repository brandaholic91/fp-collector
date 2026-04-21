# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**fp-collector** is an end-to-end first-party data collection and processing system. It is a MarTech portfolio project built as a reference implementation for collecting structured web analytics events through a self-hosted pipeline.

**Data flow:** Browser → Client tracking script → Event Collector API → PostgreSQL (`raw_events`) → n8n pipeline → `clean_events`/`leads` → Dashboard

## Stack Architecture

| Component | Role | Target Lab |
|---|---|---|
| Landing page + client tracking script | User-facing frontend, fires events | `dokploy-lab` |
| Event Collector API (`POST /v1/events`) | Receives, validates, idempotently stores events | `dokploy-lab` |
| PostgreSQL | Two-layer storage: `raw_events`, `clean_events`, `leads` | `dokploy-lab` |
| n8n workflows | Dedup, enrichment, normalization, lead routing | `martech-lab` (existing n8n) |
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

## Database Layers

- `raw_events` — ingested as-is with minimal transformation; source of truth.
- `clean_events` — validated, normalized, deduplicated by n8n.
- `leads` — optional, created from `form_submit` events by n8n.

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

## n8n Pipeline Expectations

- Trigger: new rows in `raw_events`.
- Outputs: enriched rows in `clean_events`; lead rows in `leads`; optional webhook for high-value leads.
- p95 processing latency target: < 60s.
- Failed/invalid records must be routed to a dead-letter channel (not silently dropped).

## Development Phases

1. **Phase 0** — Schema, KPI definitions, runbook skeleton
2. **Phase 1** — Collector API MVP + PostgreSQL + client tracking script
3. **Phase 2** — n8n dedup/enrichment pipeline
4. **Phase 3** — Dashboard and funnel reporting
5. **Phase 4** — Umami integration (secondary validation)
6. **Phase 5** — Portfolio packaging (README, diagrams, runbook)
