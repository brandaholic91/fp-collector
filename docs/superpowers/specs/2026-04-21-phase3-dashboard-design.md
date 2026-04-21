# fp-collector Phase 3 — Dashboard Technical Design

**Date:** 2026-04-21
**Status:** Approved

## 1. Scope

Phase 3 adds the custom dashboard UI at `/dashboard` and the backing `GET /api/stats/*` endpoints. It shows both **pipeline health** (operator view) and the **marketing conversion funnel** (business view) on a single page. A preset time range selector controls all data shown.

Real-time refresh, export features, drill-down into sessions, and comparison across time ranges are intentionally out of scope.

## 2. Tech Choices

| Concern | Choice |
|---|---|
| Styling | Tailwind CSS via CDN (no build step) |
| Charts | Chart.js via CDN (v4.4.x) |
| Frontend JS | Vanilla (no framework) |
| Data source | `clean_events` for business metrics, `raw_events` for pipeline health |
| Time range | Preset buttons: 24h / 7d / 30d / All |
| Auth | None at app level; NPM HTTP basic auth can be added later |
| Refresh | Manual only (preset button click refetches) |

Rationale: keep the architecture consistent with Phase 1 (vanilla HTML/CSS/JS served as static files by FastAPI, no build pipeline). Tailwind CDN gives modern visual polish without requiring React or a build step. Chart.js is the standard for no-build chart rendering.

## 3. Dashboard Layout

Single-page layout, desktop-first:

```
┌─────────────────────────────────────────────────────────────┐
│  fp-collector dashboard          [24h] [7d] [30d] [All]    │
├─────────────────────────────────────────────────────────────┤
│  Pipeline Health                                            │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌────────┐│
│  │ Ingested    │ │ Duplicates  │ │ Processed   │ │ Failed ││
│  │   1,523     │ │   12 (0.8%) │ │   1,511     │ │   0    ││
│  └─────────────┘ └─────────────┘ └─────────────┘ └────────┘│
├─────────────────────────────────────────────────────────────┤
│  Conversion Funnel                                          │
│  [page_view: 1,200] → [cta_click: 342] → [form_submit: 87] │
│  100%                  28.5%                7.3%            │
├──────────────────────────────┬──────────────────────────────┤
│  Events by Day               │  UTM Source / Medium         │
│  (line chart, 3 series)      │  (table: source/medium,      │
│                              │   events, leads)             │
└──────────────────────────────┴──────────────────────────────┘
```

**Components:**

1. **Header** — project name + 4 preset buttons (active preset visually highlighted).
2. **Pipeline Health** — 4 KPI cards: Ingested, Duplicates (with rate), Processed, Failed. Card order: top-down pipeline order.
3. **Conversion Funnel** — horizontal bar chart with absolute counts and conversion % from step 1.
4. **Events by Day** — line chart with three series (page_view, cta_click, form_submit), X axis = date, Y axis = count.
5. **UTM Breakdown** — sortable table: source, medium, events, leads. `null` UTMs render as `(direct)`.

## 4. API Contract

All endpoints under `/api/stats/*`. Shared query parameters:

- `from`: ISO 8601 timestamp (inclusive). Optional; omit for "all time".
- `to`: ISO 8601 timestamp (inclusive). Optional; defaults to `now()`.

Range filter SQL pattern: `WHERE occurred_at >= $from AND occurred_at <= $to` — skipped when the parameter is absent.

### 4.1 GET /api/stats/health

Pipeline health metrics from `raw_events`.

**Response:**
```json
{
  "ingested": 1523,
  "duplicates": 0,
  "duplicate_rate": 0.0,
  "processed": 1511,
  "failed": 0
}
```

**Computation:**
- `ingested` = `COUNT(*) FROM raw_events` (within time range)
- `processed` = `COUNT(*) FILTER (WHERE processed_at IS NOT NULL)`
- `failed` = `COUNT(*) FILTER (WHERE processing_error IS NOT NULL)`
- `duplicates` = **always 0** in the current implementation. Phase 1's collector API uses `ON CONFLICT (event_id) DO NOTHING` and returns `202 {"status":"duplicate"}` without creating a row. Since we don't persist duplicate attempts, we can't count them from the DB. The field is kept in the response for forward compatibility; a future iteration can log duplicates to a separate table if needed.
- `duplicate_rate` = `duplicates / max(ingested + duplicates, 1)` → also 0.0 until duplicate tracking is added.

### 4.2 GET /api/stats/funnel

Conversion funnel over unique anonymous users.

**Response:**
```json
{
  "steps": [
    {"event_name": "page_view",   "count": 1200, "conversion_from_top": 1.0},
    {"event_name": "cta_click",   "count": 342,  "conversion_from_top": 0.285},
    {"event_name": "form_submit", "count": 87,   "conversion_from_top": 0.0725}
  ]
}
```

**Computation:**
- Per step: `COUNT(DISTINCT anonymous_id) FROM clean_events WHERE event_name = $step`
- `conversion_from_top` — first step is always `1.0`. Subsequent steps: `step.count / steps[0].count`. If `steps[0].count == 0`, all `conversion_from_top` values are `null`.
- Steps are returned in fixed order: `page_view`, `cta_click`, `form_submit` — so the frontend can trust the sequence.

### 4.3 GET /api/stats/events

Daily counts per event name for the time-series chart.

**Response:**
```json
{
  "series": [
    {"date": "2026-04-20", "event_name": "page_view",   "count": 234},
    {"date": "2026-04-20", "event_name": "cta_click",   "count": 45},
    {"date": "2026-04-20", "event_name": "form_submit", "count": 12}
  ]
}
```

**Computation:** `SELECT date_trunc('day', occurred_at)::date AS date, event_name, COUNT(*) FROM clean_events GROUP BY date, event_name ORDER BY date, event_name`.

Dates with zero events for an event type are **not** returned — the frontend handles gaps by interpolating or marking as zero in the chart.

### 4.4 GET /api/stats/utm

UTM-level breakdown joined with leads.

**Response:**
```json
{
  "rows": [
    {"utm_source": "google",   "utm_medium": "cpc",    "events": 523, "leads": 12},
    {"utm_source": "facebook", "utm_medium": "social", "events": 210, "leads": 3},
    {"utm_source": null,       "utm_medium": null,     "events": 87,  "leads": 1}
  ]
}
```

**Computation:**
```sql
SELECT
    c.utm_source,
    c.utm_medium,
    COUNT(*) AS events,
    COUNT(DISTINCT l.id) AS leads
FROM clean_events c
LEFT JOIN leads l ON l.event_id = c.event_id
GROUP BY c.utm_source, c.utm_medium
ORDER BY events DESC
```

The `null, null` row represents direct traffic.

## 5. Response Status Codes

| Scenario | HTTP | Body |
|---|---|---|
| Success | 200 | See above per endpoint |
| Invalid `from`/`to` format | 422 | FastAPI default |
| DB unavailable | 503 | `{"detail": "database unavailable"}` |

No rate limiting on stats endpoints — dashboard is low-traffic and internal.

## 6. Frontend Structure

```
api/static/dashboard/
├── index.html          # Tailwind + Chart.js CDN, layout scaffold
└── app.js              # fetch + render logic, preset state management
```

No dedicated CSS file. Styling exclusively via Tailwind utility classes in `index.html`.

**`app.js` responsibilities:**

- `rangeToParams(preset)` — preset string ("24h", "7d", "30d", "all") → `{from, to}` ISO strings (or `{}` for all).
- `loadAll(preset)` — fires four parallel fetches via `Promise.all` against the four endpoints, calls the corresponding `renderX` function for each.
- `renderHealth(data)`, `renderFunnel(data)`, `renderEvents(data)`, `renderUtm(data)` — DOM updates.
- `setActivePreset(preset)` — updates `active` class on the preset nav, re-triggers `loadAll`.
- On page load: default preset is `30d`; `loadAll('30d')` fires.

**Error handling:**
- Each `renderX` function checks if the response is empty (e.g., `steps.length === 0`, `series.length === 0`). If so, renders a "No data for this range" message inside the card instead of an empty chart.
- Network errors are logged to `console.error` and the affected card shows "Failed to load".

## 7. File Changes

| File | Action |
|---|---|
| `api/routes/stats.py` | Create: four route handlers + query helpers |
| `api/models.py` | Extend: four Pydantic response models + shared optional `from`/`to` query model |
| `api/main.py` | Modify: `app.include_router(stats.router)` — one new line |
| `api/static/dashboard/index.html` | Modify: replace placeholder with Tailwind/Chart.js scaffold |
| `api/static/dashboard/app.js` | Create: fetch + render logic |
| `api/tests/test_phase3_stats.py` | Create: integration tests for all four endpoints |

## 8. Testing Strategy

`api/tests/test_phase3_stats.py` covers:

- `GET /api/stats/health` returns expected counts for a seeded dataset.
- `GET /api/stats/funnel` computes conversion_from_top correctly (including the zero-page_view edge case).
- `GET /api/stats/events` returns rows grouped by day and event_name.
- `GET /api/stats/utm` aggregates with LEFT JOIN to leads correctly, including the direct traffic row.
- Time range filtering: seed events at different timestamps, assert `from`/`to` narrows the result set.
- Empty range: assert endpoints return empty arrays / zeroed KPIs without crashing.

Frontend is not unit-tested. Smoke test: manually load `/dashboard`, verify the four cards/sections render against real data.

## 9. Security

- The dashboard is **not** authenticated at the app level.
- No PII is displayed: no emails, no anonymous_id values, no lead payloads. Only aggregated counts and UTM labels.
- The `/api/stats/*` endpoints are public by the same reasoning.
- Deployment on dokploy-lab can add HTTP basic auth at the NPM (Nginx Proxy Manager) level if the dashboard moves beyond portfolio use.

## 10. Out of Scope

- CSV / data export
- Per-session drill-down
- Time-range comparison (this week vs last week)
- Real-time refresh
- Meta CAPI integration surfacing in the dashboard (planned separately)
- Lead detail table (would require PII display and auth)
