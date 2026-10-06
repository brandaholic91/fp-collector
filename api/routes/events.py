import json
from fastapi import APIRouter, Depends, HTTPException, Request
from asyncpg import Pool

from config import settings
from db import get_pool
from limiter import limiter
from models import ECOMMERCE_EVENTS, EventRequest, EventResponse

router = APIRouter()


@router.post("/v1/events", response_model=EventResponse, status_code=202)
@limiter.limit("100/minute")
async def ingest_event(request: Request, event: EventRequest, pool: Pool = Depends(get_pool)):
    if event.event_name in ECOMMERCE_EVENTS and not settings.ecommerce_enabled:
        raise HTTPException(status_code=422, detail="unknown event_name")

    if not event.consent_analytics:
        raise HTTPException(status_code=403, detail="consent required")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO raw_events (
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, referrer, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, fbclid, consent_analytics, payload
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15
            )
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
            """,
            event.event_id,
            event.event_name,
            event.occurred_at,
            event.session_id,
            event.anonymous_id,
            event.page_url,
            event.referrer,
            event.utm_source,
            event.utm_medium,
            event.utm_campaign,
            event.utm_term,
            event.utm_content,
            event.fbclid,
            event.consent_analytics,
            json.dumps(event.payload),
        )

    if row is None:
        return EventResponse(status="duplicate")
    return EventResponse(status="ok")
