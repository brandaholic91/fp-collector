# Traffic Simulator Design

**Date:** 2026-04-22
**Status:** Approved

## Context

A continuous traffic simulator runs as a Docker service in the same compose stack, generating realistic user journey data for the fp-collector pipeline. This keeps the dashboard populated with meaningful funnel and UTM attribution data for portfolio demonstrations.

## Architecture

`api/simulator.py` runs from the existing `fp-collector-api` Docker image as a separate container. It sends HTTP POST requests to `http://api:8000/v1/events` over the `internal` Docker network — no public domain involved.

```
simulator.py
  └── POST http://api:8000/v1/events
        └── raw_events → worker → clean_events / leads → dashboard
```

## User Journey Logic

Each simulated visitor:
1. Is assigned a random traffic source (weighted)
2. Fires `page_view` (100%)
3. Fires `cta_click` with 40% probability
4. Fires `form_submit` with 25% probability (of those who clicked CTA) — ~10% overall

**Traffic source weights:**

| utm_source | utm_medium | Weight |
|------------|------------|--------|
| google     | cpc        | 35%    |
| facebook   | social     | 20%    |
| google     | organic    | 15%    |
| direct     | none       | 15%    |
| linkedin   | social     | 10%    |
| email      | newsletter | 5%     |

For `direct / none`, utm_source and utm_medium are sent as `null`.

**Timing:**
- Between visitors: random 30–180 seconds (configurable via env)
- Between journey steps: random 2–8 seconds (simulates realistic click timing)

**form_submit payload:** `{"email": "fake_user_{uuid}@example.com"}`

Each visitor gets a unique `anonymous_id` and `session_id`. Events share the same `session_id` within one journey.

## Configuration

```
SIMULATOR_COLLECTOR_URL=http://api:8000/v1/events
SIMULATOR_INTERVAL_MIN=30
SIMULATOR_INTERVAL_MAX=180
```

## Docker

New service in `docker-compose.yml`:

```yaml
simulator:
  build: ./api
  image: fp-collector-api:1.0.0
  command: python simulator.py
  env_file: .env
  depends_on:
    - api
  restart: unless-stopped
  networks:
    - internal
```

No `proxy-net` or `dokploy-network` — simulator only talks to the API over `internal`.

## Files

| Action | File |
|--------|------|
| Create | `api/simulator.py` |
| Modify | `docker-compose.yml` |
| Modify | `.env.example` |
