from datetime import timedelta

import pytest

from tests.helpers import T0, make_event, make_purchase, run_worker


@pytest.mark.asyncio
async def test_purchase_creates_one_order_and_one_link(client, ecommerce, db_pool):
    r = await client.post("/v1/events", json=make_purchase(utm_source="google", utm_medium="cpc"))
    assert r.status_code == 202
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        orders = await conn.fetch("SELECT * FROM orders")
        links = await conn.fetch("SELECT * FROM identity_links")
    assert len(orders) == 1
    assert orders[0]["order_id"] == "o-1"
    assert orders[0]["value"] == 12500
    assert orders[0]["currency"] == "HUF"
    assert orders[0]["customer_key"] == "cust-1"
    assert orders[0]["anonymous_id"] == "anon_test"
    assert orders[0]["session_id"] == "sess_test"
    assert orders[0]["source_medium"] == "google / cpc"
    assert len(links) == 1
    assert (links[0]["anonymous_id"], links[0]["customer_key"]) == ("anon_test", "cust-1")


@pytest.mark.asyncio
async def test_duplicate_purchase_keeps_one_order(client, ecommerce, db_pool):
    event = make_purchase()
    await client.post("/v1/events", json=event)
    r = await client.post("/v1/events", json=event)
    assert r.json() == {"status": "duplicate"}
    # the same order again under a new event_id (e.g. a reloaded thank-you page)
    await client.post("/v1/events", json=make_purchase())
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM orders") == 1
        assert await conn.fetchval("SELECT COUNT(*) FROM identity_links") == 1
        assert await conn.fetchval(
            "SELECT COUNT(*) FROM raw_events WHERE processing_error IS NOT NULL") == 0


@pytest.mark.asyncio
async def test_two_devices_one_customer_resolve_to_one_person(client, ecommerce, db_pool):
    batch = [
        # device A: browsing BEFORE the purchase, then the purchase
        make_event(anonymous_id="dev-A", session_id="s1", occurred_at=T0.isoformat()),
        make_purchase("o-1", "cust-1", anonymous_id="dev-A", session_id="s2",
                      occurred_at=(T0 + timedelta(days=3)).isoformat()),
        # device B: the same customer
        make_event(anonymous_id="dev-B", session_id="s3",
                   occurred_at=(T0 + timedelta(days=1)).isoformat()),
        make_purchase("o-2", "cust-1", anonymous_id="dev-B", session_id="s4",
                      occurred_at=(T0 + timedelta(days=9)).isoformat()),
        # device C: never buys
        make_event(anonymous_id="dev-C", session_id="s5"),
    ]
    r = await client.post("/v1/events/batch", json={"events": batch})
    assert r.json()["accepted"] == 5
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT anonymous_id, person_id FROM resolved_events")
        n_clean = await conn.fetchval("SELECT COUNT(*) FROM clean_events")
    assert len(rows) == n_clean == 5
    persons_by_device = {}
    for row in rows:
        persons_by_device.setdefault(row["anonymous_id"], set()).add(row["person_id"])
    assert persons_by_device == {"dev-A": {"cust-1"}, "dev-B": {"cust-1"}, "dev-C": {"dev-C"}}


@pytest.mark.asyncio
async def test_stitching_does_not_depend_on_processing_order(client, ecommerce, db_pool):
    # The purchase is processed BEFORE the earlier browsing event arrives.
    await client.post("/v1/events", json=make_purchase(anonymous_id="dev-A"))
    await run_worker(db_pool)
    await client.post("/v1/events", json=make_event(
        anonymous_id="dev-A", occurred_at=(T0 - timedelta(days=30)).isoformat()))
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        persons = await conn.fetch("SELECT DISTINCT person_id FROM resolved_events")
    assert [p["person_id"] for p in persons] == ["cust-1"]


@pytest.mark.asyncio
async def test_earliest_link_wins_when_device_has_two_customers(client, ecommerce, db_pool):
    batch = [
        make_purchase("o-late", "cust-late", anonymous_id="dev-A",
                      occurred_at=(T0 + timedelta(days=5)).isoformat()),
        make_purchase("o-early", "cust-early", anonymous_id="dev-A",
                      occurred_at=T0.isoformat()),
    ]
    await client.post("/v1/events/batch", json={"events": batch})
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        persons = await conn.fetch("SELECT DISTINCT person_id FROM resolved_events")
        n = await conn.fetchval("SELECT COUNT(*) FROM resolved_events")
    assert n == 2          # the view must not multiply rows
    assert [p["person_id"] for p in persons] == ["cust-early"]


@pytest.mark.asyncio
async def test_link_keeps_the_earliest_first_seen(client, ecommerce, db_pool):
    await client.post("/v1/events", json=make_purchase(
        "o-2", occurred_at=(T0 + timedelta(days=5)).isoformat()))
    await run_worker(db_pool)
    await client.post("/v1/events", json=make_purchase("o-1", occurred_at=T0.isoformat()))
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        links = await conn.fetch("SELECT first_seen_at FROM identity_links")
    assert [link["first_seen_at"] for link in links] == [T0]
