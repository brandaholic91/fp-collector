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

# Every event carries this, so synthetic rows can be told apart from real traffic.
SIMULATED = {"simulated": True}


def pick_source() -> dict:
    return random.choices(SOURCES, weights=WEIGHTS, k=1)[0]


def build_journey(source: dict) -> list[dict]:
    anonymous_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
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
        "payload": {**SIMULATED},
    }]

    if random.random() < 0.40:
        events.append({
            **base,
            "event_id": str(uuid.uuid4()),
            "event_name": "cta_click",
            "payload": {"label": "hero_dashboard", **SIMULATED},
        })

        if random.random() < 0.25:
            events.append({
                **base,
                "event_id": str(uuid.uuid4()),
                "event_name": "form_submit",
                "payload": {"email": f"fake_user_{str(uuid.uuid4())[:8]}@example.com", **SIMULATED},
            })

    return events


async def send_event(client: httpx.AsyncClient, event: dict) -> None:
    try:
        response = await client.post(COLLECTOR_URL, json=event)
        response.raise_for_status()
    except Exception as exc:
        print(f"Failed to send event {event.get('event_name')}: {exc}")


async def run_visitor() -> None:
    source = pick_source()
    events = build_journey(source)
    async with httpx.AsyncClient(timeout=10) as client:
        for event in events:
            event["occurred_at"] = datetime.now(timezone.utc).isoformat()
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
