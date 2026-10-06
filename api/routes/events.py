import json
from fastapi import APIRouter, Depends, HTTPException, Request
from asyncpg import Pool

from config import settings
from db import get_pool
from limiter import limiter
from models import (
    ECOMMERCE_EVENTS, BatchRequest, BatchResponse, EventRequest, EventResponse,
)

router = APIRouter()


def require_ecommerce():
    # A dependency runs before the body is validated, so with the flag off the
    # endpoint is a plain 404 whatever was posted.
    if not settings.ecommerce_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


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


@router.post(
    "/v1/events/batch",
    response_model=BatchResponse,
    status_code=202,
    dependencies=[Depends(require_ecommerce)],
)
async def ingest_batch(batch: BatchRequest, pool: Pool = Depends(get_pool)):
    consented = [e for e in batch.events if e.consent_analytics]
    consent_rejected = len(batch.events) - len(consented)
    if not consented:
        return BatchResponse(accepted=0, duplicates=0, consent_rejected=consent_rejected)

    # One array per column; unnest() zips them back into rows, so the whole
    # batch is a single INSERT regardless of its size.
    columns = list(zip(*[
        (
            e.event_id, e.event_name, e.occurred_at, e.session_id, e.anonymous_id,
            e.page_url, e.referrer, e.utm_source, e.utm_medium, e.utm_campaign,
            e.utm_term, e.utm_content, e.fbclid, json.dumps(e.payload),
        )
        for e in consented
    ]))
    async with pool.acquire() as conn:
        inserted = await conn.fetch(
            """
            INSERT INTO raw_events (
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, referrer, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, fbclid, consent_analytics, payload
            )
            SELECT t.event_id, t.event_name, t.occurred_at, t.session_id, t.anonymous_id,
                   t.page_url, t.referrer, t.utm_source, t.utm_medium, t.utm_campaign,
                   t.utm_term, t.utm_content, t.fbclid, true, t.payload::jsonb
            FROM unnest(
                $1::uuid[], $2::text[], $3::timestamptz[], $4::text[], $5::text[],
                $6::text[], $7::text[], $8::text[], $9::text[], $10::text[],
                $11::text[], $12::text[], $13::text[], $14::text[]
            ) AS t(
                event_id, event_name, occurred_at, session_id, anonymous_id,
                page_url, referrer, utm_source, utm_medium, utm_campaign,
                utm_term, utm_content, fbclid, payload
            )
            ON CONFLICT (event_id) DO NOTHING
            RETURNING 1
            """,
            *[list(c) for c in columns],
        )

    # ON CONFLICT DO NOTHING returns no row for a duplicate, whether it was
    # already stored or repeated inside this batch.
    accepted = len(inserted)
    return BatchResponse(
        accepted=accepted,
        duplicates=len(consented) - accepted,
        consent_rejected=consent_rejected,
    )
