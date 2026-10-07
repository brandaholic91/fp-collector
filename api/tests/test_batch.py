import pytest

from tests.helpers import T0, make_event, make_purchase


# --- flag off: the endpoint does not exist --------------------------------

@pytest.mark.asyncio
async def test_flag_off_batch_is_404(client):
    r = await client.post("/v1/events/batch", json={"events": [make_event()]})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_flag_off_batch_is_404_even_for_malformed_body(client):
    r = await client.post("/v1/events/batch", json={"nonsense": True})
    assert r.status_code == 404


# --- flag on ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_batch_counts_new_duplicate_and_consentless(client, ecommerce, db_pool):
    old = make_event()
    await client.post("/v1/events", json=old)
    new1, new2 = make_event(), make_event(event_name="view_item")
    batch = [
        new1, new2,
        old,                                    # already stored
        new1,                                   # repeated inside the batch
        make_event(consent_analytics=False),
    ]
    r = await client.post("/v1/events/batch", json={"events": batch})
    assert r.status_code == 202
    assert r.json() == {"accepted": 2, "duplicates": 2, "consent_rejected": 1}
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM raw_events") == 3
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM raw_events WHERE NOT consent_analytics") == 0


@pytest.mark.asyncio
async def test_batch_with_only_consentless_events_stores_nothing(client, ecommerce, db_pool):
    r = await client.post("/v1/events/batch",
                          json={"events": [make_event(consent_analytics=False)]})
    assert r.json() == {"accepted": 0, "duplicates": 0, "consent_rejected": 1}
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM raw_events") == 0


@pytest.mark.asyncio
async def test_batch_one_malformed_item_rejects_whole_batch(client, ecommerce, db_pool):
    bad = make_event(event_name="purchase", payload={"order_id": "o"})
    r = await client.post("/v1/events/batch", json={"events": [make_event(), bad]})
    assert r.status_code == 422
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM raw_events") == 0


@pytest.mark.asyncio
async def test_batch_size_limits(client, ecommerce):
    r = await client.post("/v1/events/batch", json={"events": []})
    assert r.status_code == 422
    r = await client.post("/v1/events/batch",
                          json={"events": [make_event() for _ in range(1001)]})
    assert r.status_code == 422
    r = await client.post("/v1/events/batch",
                          json={"events": [make_event() for _ in range(1000)]})
    assert r.status_code == 202
    assert r.json()["accepted"] == 1000


@pytest.mark.asyncio
async def test_batch_is_not_rate_limited(client, ecommerce):
    for _ in range(105):
        r = await client.post("/v1/events/batch", json={"events": [make_event()]})
        assert r.status_code == 202


@pytest.mark.asyncio
async def test_batch_preserves_fields_and_payload(client, ecommerce, db_pool):
    e = make_purchase(utm_source="newsletter", utm_medium="email",
                      referrer="https://www.google.com/")
    await client.post("/v1/events/batch", json={"events": [e]})
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM raw_events")
    assert str(row["event_id"]) == e["event_id"]
    assert row["occurred_at"] == T0
    assert row["utm_source"] == "newsletter"
    assert row["referrer"] == "https://www.google.com/"
    assert row["fbclid"] is None
    assert '"order_id": "o-1"' in row["payload"]
