import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest


PIPELINE_WAIT_SECONDS = int(os.environ.get("PHASE2_PIPELINE_WAIT", "45"))


async def _seed_events(pool, events):
    async with pool.acquire() as conn:
        for e in events:
            await conn.execute(
                """
                INSERT INTO raw_events (
                    event_id, event_name, occurred_at, session_id, anonymous_id,
                    page_url, referrer, utm_source, utm_medium, utm_campaign,
                    fbclid, consent_analytics, payload
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, true, $12::jsonb)
                """,
                e["event_id"], e["event_name"], e["occurred_at"], e["session_id"],
                e["anonymous_id"], e["page_url"], e.get("referrer"),
                e.get("utm_source"), e.get("utm_medium"), e.get("utm_campaign"),
                e.get("fbclid"), e.get("payload", "{}"),
            )


@pytest.mark.skipif(
    os.environ.get("PHASE2_SMOKE") != "1",
    reason="Phase 2 smoke test only runs against a live n8n pipeline (set PHASE2_SMOKE=1)",
)
@pytest.mark.asyncio
async def test_end_to_end_pipeline(db_pool):
    now = datetime.now(timezone.utc)
    events = [
        {
            "event_id": uuid.uuid4(),
            "event_name": "page_view",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring_sale",
        },
        {
            "event_id": uuid.uuid4(),
            "event_name": "cta_click",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/",
            "referrer": "https://www.facebook.com/",
        },
        {
            "event_id": uuid.uuid4(),
            "event_name": "form_submit",
            "occurred_at": now,
            "session_id": "smoke-sess",
            "anonymous_id": "smoke-anon",
            "page_url": "https://example.com/thanks",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "spring_sale",
            "payload": '{"email": "smoke@example.com"}',
        },
    ]
    await _seed_events(db_pool, events)

    await asyncio.sleep(PIPELINE_WAIT_SECONDS)

    event_ids = [e["event_id"] for e in events]
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT event_id, processed_at, processing_error FROM raw_events WHERE event_id = ANY($1)",
            event_ids,
        )
        assert len(rows) == 3
        for r in rows:
            assert r["processed_at"] is not None, f"not processed: {r['event_id']}"
            assert r["processing_error"] is None, f"has error: {r['processing_error']}"

        clean = {
            r["event_id"]: r
            for r in await conn.fetch(
                "SELECT event_id, source_medium FROM clean_events WHERE event_id = ANY($1)",
                event_ids,
            )
        }
        assert len(clean) == 3
        assert clean[events[0]["event_id"]]["source_medium"] == "google / cpc"
        assert clean[events[1]["event_id"]]["source_medium"] == "facebook / referral"
        assert clean[events[2]["event_id"]]["source_medium"] == "google / cpc"

        leads = await conn.fetch(
            "SELECT event_id, payload FROM leads WHERE event_id = ANY($1)",
            event_ids,
        )
        assert len(leads) == 1
        assert leads[0]["event_id"] == events[2]["event_id"]
        import json
        payload = json.loads(leads[0]["payload"]) if isinstance(leads[0]["payload"], str) else leads[0]["payload"]
        assert payload["email"] == "smoke@example.com"
