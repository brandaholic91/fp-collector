from datetime import datetime
from typing import Optional

from asyncpg import Pool
from fastapi import APIRouter, Depends, Query

from db import get_pool
from models import (
    HealthResponse, FunnelResponse, FunnelStep,
    EventsResponse, EventSeriesRow,
    UtmResponse, UtmRow,
)

router = APIRouter(prefix="/api/stats")


def _range_filter(column: str, from_: Optional[datetime], to: Optional[datetime]):
    clauses, params = [], []
    if from_ is not None:
        params.append(from_)
        clauses.append(f"{column} >= ${len(params)}")
    if to is not None:
        params.append(to)
        clauses.append(f"{column} <= ${len(params)}")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


@router.get("/health", response_model=HealthResponse)
async def stats_health(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT
            COUNT(*) AS ingested,
            COUNT(*) FILTER (
                WHERE processed_at IS NULL AND processing_error IS NULL
            ) AS pending,
            COUNT(*) FILTER (WHERE processed_at IS NOT NULL) AS processed,
            COUNT(*) FILTER (WHERE processing_error IS NOT NULL) AS failed
        FROM raw_events
        {where}
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)
    return HealthResponse(
        ingested=row["ingested"],
        pending=row["pending"],
        processed=row["processed"],
        failed=row["failed"],
    )


FUNNEL_STEPS = ["page_view", "cta_click", "form_submit"]


@router.get("/funnel", response_model=FunnelResponse)
async def stats_funnel(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT event_name, COUNT(DISTINCT anonymous_id) AS count
        FROM clean_events
        {where}
        GROUP BY event_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    counts = {r["event_name"]: r["count"] for r in rows}

    top = counts.get(FUNNEL_STEPS[0], 0)
    steps = []
    for name in FUNNEL_STEPS:
        count = counts.get(name, 0)
        conv = (count / top) if top > 0 else None
        steps.append(FunnelStep(event_name=name, count=count, conversion_from_top=conv))
    return FunnelResponse(steps=steps)


@router.get("/events", response_model=EventsResponse)
async def stats_events(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("occurred_at", from_, to)
    query = f"""
        SELECT
            date_trunc('day', occurred_at)::date AS date,
            event_name,
            COUNT(*) AS count
        FROM clean_events
        {where}
        GROUP BY date, event_name
        ORDER BY date, event_name
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    series = [
        EventSeriesRow(
            date=r["date"].isoformat(),
            event_name=r["event_name"],
            count=r["count"],
        )
        for r in rows
    ]
    return EventsResponse(series=series)


@router.get("/utm", response_model=UtmResponse)
async def stats_utm(
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    pool: Pool = Depends(get_pool),
):
    where, params = _range_filter("c.occurred_at", from_, to)
    query = f"""
        SELECT
            c.utm_source,
            c.utm_medium,
            COUNT(*) AS events,
            COUNT(DISTINCT l.id) AS leads
        FROM clean_events c
        LEFT JOIN leads l ON l.event_id = c.event_id
        {where}
        GROUP BY c.utm_source, c.utm_medium
        ORDER BY events DESC
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    return UtmResponse(rows=[
        UtmRow(
            utm_source=r["utm_source"],
            utm_medium=r["utm_medium"],
            events=r["events"],
            leads=r["leads"],
        )
        for r in rows
    ])
