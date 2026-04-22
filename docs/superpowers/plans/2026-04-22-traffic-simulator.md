# Traffic Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a continuous traffic simulator that runs as a Docker service and sends realistic user journey events to the collector API.

**Architecture:** `api/simulator.py` runs from the existing API image with `command: python simulator.py`. Pure logic functions (`pick_source`, `build_journey`) are separated from the async run loop so they can be unit tested without HTTP. Events are POSTed to `http://api:8000/v1/events` over the `internal` Docker network.

**Tech Stack:** Python 3.11, asyncio, httpx (already in requirements.txt)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `api/simulator.py` | Source selection, journey building, async poll loop |
| Create | `api/tests/test_simulator.py` | Unit tests for pure functions |
| Modify | `docker-compose.yml` | Add `simulator` service |
| Modify | `.env.example` | Document simulator env vars |

---

## Task 1: Implement pure logic with tests (TDD)

**Files:**
- Create: `api/tests/test_simulator.py`
- Create: `api/simulator.py`

- [ ] **Step 1: Create `api/tests/test_simulator.py`**

```python
import pytest
from simulator import pick_source, build_journey, SOURCES, WEIGHTS


def test_pick_source_returns_valid_source():
    source = pick_source()
    assert isinstance(source, dict)
    assert "utm_source" in source
    assert "utm_medium" in source
    assert "utm_campaign" in source


def test_pick_source_weights_sum_to_100():
    assert sum(WEIGHTS) == 100


def test_pick_source_direct_has_null_utm():
    # Run many times to ensure direct (null UTM) appears
    sources = [pick_source() for _ in range(200)]
    direct = [s for s in sources if s["utm_source"] is None]
    assert len(direct) > 0


def test_build_journey_always_starts_with_page_view():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    journey = build_journey(source)
    assert len(journey) >= 1
    assert journey[0]["event_name"] == "page_view"


def test_build_journey_page_view_has_correct_fields():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "brand"}
    journey = build_journey(source)
    pv = journey[0]
    assert pv["utm_source"] == "google"
    assert pv["utm_medium"] == "cpc"
    assert pv["consent_analytics"] is True
    assert pv["event_id"] is not None
    assert pv["session_id"] is not None
    assert pv["anonymous_id"] is not None


def test_build_journey_no_form_submit_without_cta_click():
    source = {"utm_source": None, "utm_medium": None, "utm_campaign": None}
    for _ in range(50):
        journey = build_journey(source)
        names = [e["event_name"] for e in journey]
        if "form_submit" in names:
            assert "cta_click" in names


def test_build_journey_all_events_share_session_and_anon_id():
    source = {"utm_source": "facebook", "utm_medium": "social", "utm_campaign": "test"}
    # Run multiple times to get a journey with multiple events
    for _ in range(20):
        journey = build_journey(source)
        if len(journey) > 1:
            session_ids = {e["session_id"] for e in journey}
            anon_ids = {e["anonymous_id"] for e in journey}
            assert len(session_ids) == 1
            assert len(anon_ids) == 1
            break


def test_build_journey_form_submit_has_email_payload():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    found_form_submit = False
    for _ in range(100):
        journey = build_journey(source)
        for event in journey:
            if event["event_name"] == "form_submit":
                assert "email" in event["payload"]
                assert "@example.com" in event["payload"]["email"]
                found_form_submit = True
                break
        if found_form_submit:
            break
    # It's probabilistic — just verify the structure if we found one


def test_build_journey_event_ids_are_unique():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    for _ in range(20):
        journey = build_journey(source)
        if len(journey) > 1:
            ids = [e["event_id"] for e in journey]
            assert len(ids) == len(set(ids))
            break
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_simulator.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'simulator'`

- [ ] **Step 3: Create `api/simulator.py` with pure functions**

```python
import asyncio
import os
import random
import uuid
from datetime import datetime, timezone

import httpx

COLLECTOR_URL = os.environ.get("SIMULATOR_COLLECTOR_URL", "http://api:8000/v1/events")
INTERVAL_MIN = int(os.environ.get("SIMULATOR_INTERVAL_MIN", "30"))
INTERVAL_MAX = int(os.environ.get("SIMULATOR_INTERVAL_MAX", "180"))

SOURCES = [
    {"utm_source": "google",   "utm_medium": "cpc",        "utm_campaign": "brand_search"},
    {"utm_source": "facebook", "utm_medium": "social",     "utm_campaign": "awareness"},
    {"utm_source": "google",   "utm_medium": "organic",    "utm_campaign": None},
    {"utm_source": None,       "utm_medium": None,         "utm_campaign": None},
    {"utm_source": "linkedin", "utm_medium": "social",     "utm_campaign": "b2b_reach"},
    {"utm_source": "email",    "utm_medium": "newsletter", "utm_campaign": "weekly_digest"},
]

WEIGHTS = [35, 20, 15, 15, 10, 5]


def pick_source() -> dict:
    return random.choices(SOURCES, weights=WEIGHTS, k=1)[0]


def build_journey(source: dict) -> list[dict]:
    anonymous_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "session_id": session_id,
        "anonymous_id": anonymous_id,
        "page_url": "https://fp.growthframe.hu/",
        "referrer": None,
        "consent_analytics": True,
        **source,
    }

    events = [{
        **base,
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": now,
        "payload": {},
    }]

    if random.random() < 0.40:
        events.append({
            **base,
            "event_id": str(uuid.uuid4()),
            "event_name": "cta_click",
            "occurred_at": now,
            "payload": {"label": "hero_dashboard"},
        })

        if random.random() < 0.25:
            events.append({
                **base,
                "event_id": str(uuid.uuid4()),
                "event_name": "form_submit",
                "occurred_at": now,
                "payload": {"email": f"fake_user_{str(uuid.uuid4())[:8]}@example.com"},
            })

    return events


async def send_event(client: httpx.AsyncClient, event: dict) -> None:
    try:
        await client.post(COLLECTOR_URL, json=event)
    except Exception as exc:
        print(f"Failed to send event {event.get('event_name')}: {exc}")


async def run_visitor() -> None:
    source = pick_source()
    events = build_journey(source)
    async with httpx.AsyncClient(timeout=10) as client:
        for event in events:
            await send_event(client, event)
            if len(events) > 1:
                await asyncio.sleep(random.uniform(2, 8))


async def run() -> None:
    print(f"Simulator started — interval: {INTERVAL_MIN}–{INTERVAL_MAX}s, target: {COLLECTOR_URL}")
    while True:
        await run_visitor()
        delay = random.uniform(INTERVAL_MIN, INTERVAL_MAX)
        await asyncio.sleep(delay)


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd /home/brandaholic/Playground/fp-collector/api
pytest tests/test_simulator.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Verify import**

```bash
cd /home/brandaholic/Playground/fp-collector/api
python -c "import simulator; print('ok')"
```

Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add api/simulator.py api/tests/test_simulator.py
git commit -m "feat: add traffic simulator with user journey logic"
```

---

## Task 2: Add simulator service to docker-compose and .env.example

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add `simulator` service to `docker-compose.yml` after the `worker` service block**

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

- [ ] **Step 2: Add simulator env vars to `.env.example`** after the `WORKER_POLL_INTERVAL` line:

```
SIMULATOR_COLLECTOR_URL=http://api:8000/v1/events
SIMULATOR_INTERVAL_MIN=30
SIMULATOR_INTERVAL_MAX=180
```

- [ ] **Step 3: Validate compose syntax**

```bash
cd /home/brandaholic/Playground/fp-collector
docker compose config --quiet && echo "ok"
```

Expected: `ok`

- [ ] **Step 4: Commit and push**

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add simulator service to docker-compose"
git push
```
