import json
import uuid
from datetime import timedelta

import pytest

from tests.helpers import T0


@pytest.fixture
def batched(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "worker_batched", True)


async def insert_raw(conn, event_name="page_view", payload=None, **kw):
    row = {
        "event_id": uuid.uuid4(), "occurred_at": T0, "session_id": "s1",
        "anonymous_id": "dev-A", "page_url": "https://bolt.example/",
        "referrer": None, "utm_source": None, "utm_medium": None, "utm_campaign": None,
    }
    row.update(kw)
    await conn.execute(
        """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, referrer, utm_source, utm_medium, utm_campaign,
               consent_analytics, payload)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,true,$11::jsonb)""",
        row["event_id"], event_name, row["occurred_at"], row["session_id"],
        row["anonymous_id"], row["page_url"], row["referrer"], row["utm_source"],
        row["utm_medium"], row["utm_campaign"], json.dumps(payload or {}),
    )
    return row["event_id"]


def purchase(order_id, customer_key="cust-1", value=9900):
    return {"order_id": order_id, "value": value, "currency": "HUF",
            "customer_key": customer_key}


async def seed_mixed(conn):
    await insert_raw(conn, utm_source="Google", utm_medium="CPC", utm_campaign="")
    await insert_raw(conn, referrer="https://www.google.com/search?q=x")
    await insert_raw(conn, "view_item")
    await insert_raw(conn, "form_submit", {"email": "a@example.com"},
                     utm_source="newsletter", utm_medium="email")
    await insert_raw(conn, "purchase", purchase("o-1"),
                     occurred_at=T0 + timedelta(days=2))
    await insert_raw(conn, "purchase", purchase("o-2"), occurred_at=T0)   # same pair again
    await insert_raw(conn, "purchase", purchase("o-1"))                   # repeated order
    await insert_raw(conn, "purchase", purchase("o-3", "cust-2"), anonymous_id="dev-B")


async def snapshot(conn):
    return {
        "clean": [tuple(r.values()) for r in await conn.fetch(
            """SELECT event_name, occurred_at, session_id, anonymous_id, referrer,
                      utm_source, utm_medium, utm_campaign, source_medium, payload
               FROM clean_events ORDER BY raw_event_id""")],
        "leads": [tuple(r.values()) for r in await conn.fetch(
            "SELECT anonymous_id, utm_source, utm_medium, payload FROM leads ORDER BY id")],
        "orders": [tuple(r.values()) for r in await conn.fetch(
            """SELECT order_id, value, currency, customer_key, anonymous_id, session_id,
                      occurred_at, source_medium FROM orders ORDER BY order_id""")],
        "links": [tuple(r.values()) for r in await conn.fetch(
            """SELECT anonymous_id, customer_key, first_seen_at FROM identity_links
               ORDER BY anonymous_id, customer_key""")],
        "raw": [tuple(r.values()) for r in await conn.fetch(
            """SELECT processed_at IS NOT NULL, processing_error FROM raw_events
               ORDER BY id""")],
    }


@pytest.mark.asyncio
async def test_batched_mode_gives_the_same_tables_as_per_event(db_pool, monkeypatch):
    from config import settings
    from worker import process_batch

    snapshots = []
    for batched_mode in (False, True):
        monkeypatch.setattr(settings, "worker_batched", batched_mode)
        async with db_pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE raw_events, clean_events, leads, orders, identity_links "
                "RESTART IDENTITY CASCADE")
            await seed_mixed(conn)
        while await process_batch(db_pool):
            pass
        async with db_pool.acquire() as conn:
            snapshots.append(await snapshot(conn))

    per_event, batched = snapshots
    assert batched == per_event
    assert len(batched["clean"]) == 8
    assert len(batched["leads"]) == 1
    assert [o[0] for o in batched["orders"]] == ["o-1", "o-2", "o-3"]
    assert batched["links"] == [("dev-A", "cust-1", T0), ("dev-B", "cust-2", T0)]
    assert batched["raw"] == [(True, None)] * 8


@pytest.mark.asyncio
async def test_batched_mode_makes_one_pass_over_many_rows(db_pool, batched):
    from worker import process_batch
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
                   anonymous_id, page_url, consent_analytics)
               SELECT gen_random_uuid(), 'page_view', now(), 's', 'a',
                      'https://bolt.example/', true
               FROM generate_series(1, 1200)""")
    assert await process_batch(db_pool) == 1200
    assert await process_batch(db_pool) == 0
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM clean_events") == 1200


@pytest.mark.asyncio
async def test_bad_row_falls_back_and_only_that_row_gets_an_error(db_pool, batched):
    from worker import process_batch
    async with db_pool.acquire() as conn:
        good1 = await insert_raw(conn)
        bad = await insert_raw(conn, "purchase", {
            "order_id": "o-x", "value": "not a number", "currency": "HUF",
            "customer_key": "c"})
        good2 = await insert_raw(conn, "purchase", purchase("o-ok"))
    await process_batch(db_pool)
    async with db_pool.acquire() as conn:
        state = {r["event_id"]: (r["processed_at"] is not None, r["processing_error"])
                   for r in await conn.fetch("SELECT * FROM raw_events")}
        orders = await conn.fetch("SELECT order_id FROM orders")
    assert state[good1] == (True, None)
    assert state[good2] == (True, None)
    assert state[bad][0] is False and state[bad][1]
    assert [o["order_id"] for o in orders] == ["o-ok"]
