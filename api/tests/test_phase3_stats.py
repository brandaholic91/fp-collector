import uuid
from datetime import datetime, timedelta, timezone

import pytest


async def _insert_raw(conn, event_name="page_view", occurred_at=None,
                     processed=False, failed=False):
    occurred_at = occurred_at or datetime.now(timezone.utc)
    processed_at = occurred_at if processed else None
    processing_error = "test error" if failed else None
    await conn.execute(
        """
        INSERT INTO raw_events (
            event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, consent_analytics, payload, processed_at, processing_error
        ) VALUES ($1, $2, $3, 'sess', 'anon', 'https://x/', true, '{}', $4, $5)
        """,
        uuid.uuid4(), event_name, occurred_at, processed_at, processing_error,
    )


@pytest.mark.asyncio
async def test_health_returns_zeros_for_empty_db(client):
    response = await client.get("/api/stats/health")
    assert response.status_code == 200
    assert response.json() == {
        "ingested": 0,
        "pending": 0,
        "processed": 0,
        "failed": 0,
    }


@pytest.mark.asyncio
async def test_health_counts_ingested_processed_failed(client, db_pool):
    async with db_pool.acquire() as conn:
        await _insert_raw(conn)                      # pending
        await _insert_raw(conn, processed=True)      # processed
        await _insert_raw(conn, processed=True)      # processed
        await _insert_raw(conn, failed=True)         # failed

    response = await client.get("/api/stats/health")
    data = response.json()
    assert data["ingested"] == 4
    assert data["processed"] == 2
    assert data["failed"] == 1
    assert data["pending"] == 1


@pytest.mark.asyncio
async def test_health_respects_time_range_filter(client, db_pool):
    now = datetime.now(timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_raw(conn, occurred_at=now - timedelta(days=10))
        await _insert_raw(conn, occurred_at=now - timedelta(days=1))
        await _insert_raw(conn, occurred_at=now)

    from_ts = (now - timedelta(days=2)).isoformat()
    response = await client.get("/api/stats/health", params={"from": from_ts})
    assert response.json()["ingested"] == 2


async def _insert_clean(conn, event_name, anonymous_id,
                        occurred_at=None, utm_source=None,
                        utm_medium=None, utm_campaign=None,
                        source_medium="direct / none"):
    occurred_at = occurred_at or datetime.now(timezone.utc)
    event_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO clean_events (
            event_id, event_name, occurred_at, session_id, anonymous_id,
            page_url, utm_source, utm_medium, utm_campaign,
            source_medium, payload
        ) VALUES ($1, $2, $3, 'sess', $4, 'https://x/', $5, $6, $7, $8, '{}')
        """,
        event_id, event_name, occurred_at, anonymous_id,
        utm_source, utm_medium, utm_campaign, source_medium,
    )
    return event_id


@pytest.mark.asyncio
async def test_funnel_returns_zero_counts_for_empty_db(client):
    response = await client.get("/api/stats/funnel")
    assert response.status_code == 200
    steps = response.json()["steps"]
    assert [s["event_name"] for s in steps] == ["page_view", "cta_click", "form_submit"]
    for step in steps:
        assert step["count"] == 0
        assert step["conversion_from_top"] is None


@pytest.mark.asyncio
async def test_funnel_counts_distinct_anonymous_per_step(client, db_pool):
    async with db_pool.acquire() as conn:
        for anon in ["a", "b", "c", "d"]:
            await _insert_clean(conn, "page_view", anon)
        await _insert_clean(conn, "page_view", "a")  # repeat → still 4 distinct
        for anon in ["a", "b"]:
            await _insert_clean(conn, "cta_click", anon)
        await _insert_clean(conn, "form_submit", "a")

    response = await client.get("/api/stats/funnel")
    steps = {s["event_name"]: s for s in response.json()["steps"]}
    assert steps["page_view"]["count"] == 4
    assert steps["page_view"]["conversion_from_top"] == 1.0
    assert steps["cta_click"]["count"] == 2
    assert steps["cta_click"]["conversion_from_top"] == 0.5
    assert steps["form_submit"]["count"] == 1
    assert steps["form_submit"]["conversion_from_top"] == 0.25


@pytest.mark.asyncio
async def test_events_returns_empty_series_for_empty_db(client):
    response = await client.get("/api/stats/events")
    assert response.status_code == 200
    assert response.json() == {"series": []}


@pytest.mark.asyncio
async def test_events_groups_by_day_and_event_name(client, db_pool):
    day1 = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    day2 = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_clean(conn, "page_view", "a", occurred_at=day1)
        await _insert_clean(conn, "page_view", "b", occurred_at=day1)
        await _insert_clean(conn, "cta_click", "a", occurred_at=day1)
        await _insert_clean(conn, "page_view", "c", occurred_at=day2)

    response = await client.get("/api/stats/events")
    series = response.json()["series"]
    rows = {(r["date"], r["event_name"]): r["count"] for r in series}
    assert rows[("2026-04-10", "page_view")] == 2
    assert rows[("2026-04-10", "cta_click")] == 1
    assert rows[("2026-04-11", "page_view")] == 1
    assert len(series) == 3


@pytest.mark.asyncio
async def test_events_respects_time_range_filter(client, db_pool):
    old = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    new = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    async with db_pool.acquire() as conn:
        await _insert_clean(conn, "page_view", "a", occurred_at=old)
        await _insert_clean(conn, "page_view", "b", occurred_at=new)

    response = await client.get("/api/stats/events", params={"from": "2026-04-01T00:00:00Z"})
    series = response.json()["series"]
    assert len(series) == 1
    assert series[0]["date"] == "2026-04-10"


@pytest.mark.asyncio
async def test_utm_returns_empty_rows_for_empty_db(client):
    response = await client.get("/api/stats/utm")
    assert response.status_code == 200
    assert response.json() == {"rows": []}


@pytest.mark.asyncio
async def test_utm_aggregates_events_and_joins_leads(client, db_pool):
    async with db_pool.acquire() as conn:
        # Two google/cpc events, one of which has a lead
        google_event_id = await _insert_clean(
            conn, "form_submit", "a",
            utm_source="google", utm_medium="cpc", utm_campaign="spring",
        )
        await _insert_clean(
            conn, "page_view", "b",
            utm_source="google", utm_medium="cpc", utm_campaign="spring",
        )
        # Direct traffic (no UTM)
        await _insert_clean(conn, "page_view", "c")
        # Facebook social, no lead
        await _insert_clean(
            conn, "cta_click", "d",
            utm_source="facebook", utm_medium="social",
        )
        # Insert one lead referencing the google form_submit
        await conn.execute(
            """
            INSERT INTO leads (event_id, anonymous_id, occurred_at, payload)
            VALUES ($1, 'a', now(), '{}')
            """,
            google_event_id,
        )

    response = await client.get("/api/stats/utm")
    rows = response.json()["rows"]
    by_key = {(r["utm_source"], r["utm_medium"]): r for r in rows}

    assert by_key[("google", "cpc")]["events"] == 2
    assert by_key[("google", "cpc")]["leads"] == 1
    assert by_key[("facebook", "social")]["events"] == 1
    assert by_key[("facebook", "social")]["leads"] == 0
    assert by_key[(None, None)]["events"] == 1
    assert by_key[(None, None)]["leads"] == 0


@pytest.mark.asyncio
async def test_utm_rows_sorted_by_events_desc(client, db_pool):
    async with db_pool.acquire() as conn:
        for _ in range(3):
            await _insert_clean(conn, "page_view", uuid.uuid4().hex,
                                utm_source="big", utm_medium="cpc")
        await _insert_clean(conn, "page_view", "x",
                            utm_source="small", utm_medium="cpc")

    response = await client.get("/api/stats/utm")
    rows = response.json()["rows"]
    assert rows[0]["utm_source"] == "big"
    assert rows[0]["events"] == 3
