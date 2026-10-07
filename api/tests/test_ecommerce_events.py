import pathlib

import pytest

from tests.helpers import make_event, make_purchase


# --- flag off: production behaviour ---------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["view_item", "add_to_cart", "begin_checkout"])
async def test_flag_off_rejects_ecommerce_events(client, name):
    r = await client.post("/v1/events", json=make_event(event_name=name))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_flag_off_rejects_purchase_and_stores_nothing(client, db_pool):
    r = await client.post("/v1/events", json=make_purchase())
    assert r.status_code == 422
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM raw_events") == 0


# --- flag on ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_flag_on_accepts_ecommerce_events(client, ecommerce):
    for name in ("view_item", "add_to_cart", "begin_checkout"):
        r = await client.post("/v1/events", json=make_event(event_name=name))
        assert r.status_code == 202, name


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {},
    {"value": 100, "currency": "HUF", "customer_key": "c"},          # no order_id
    {"order_id": "o", "currency": "HUF", "customer_key": "c"},       # no value
    {"order_id": "o", "value": 100, "customer_key": "c"},            # no currency
    {"order_id": "o", "value": 100, "currency": "HUF"},              # no customer_key
    {"order_id": "o", "value": 0, "currency": "HUF", "customer_key": "c"},
    {"order_id": "o", "value": -5, "currency": "HUF", "customer_key": "c"},
    {"order_id": "o", "value": "100", "currency": "HUF", "customer_key": "c"},
    {"order_id": "o", "value": True, "currency": "HUF", "customer_key": "c"},
    {"order_id": "", "value": 100, "currency": "HUF", "customer_key": "c"},
])
async def test_incomplete_purchase_is_422_and_stores_nothing(client, ecommerce, db_pool, payload):
    r = await client.post("/v1/events", json=make_event(event_name="purchase", payload=payload))
    assert r.status_code == 422
    async with db_pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM raw_events") == 0


# --- schema ----------------------------------------------------------------

DB_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "db"


def test_migration_004_is_the_tail_of_init_sql():
    # A fresh instance gets init.sql, an existing one gets the migration:
    # the two must not drift apart.
    migration = (DB_DIR / "migrations" / "004_ecommerce.sql").read_text()
    assert migration.strip()
    assert (DB_DIR / "init.sql").read_text().endswith(migration)


@pytest.mark.asyncio
async def test_migration_004_is_idempotent_and_creates_the_objects(db_pool):
    migration = (DB_DIR / "migrations" / "004_ecommerce.sql").read_text()
    async with db_pool.acquire() as conn:
        await conn.execute(migration)
        await conn.execute(migration)
        tables = {r["table_name"] for r in await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
        view_columns = [r["column_name"] for r in await conn.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'resolved_events' ORDER BY ordinal_position""")]
        clean_columns = [r["column_name"] for r in await conn.fetch(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'clean_events' ORDER BY ordinal_position""")]
    assert {"orders", "identity_links", "resolved_events"} <= tables
    assert view_columns == clean_columns + ["person_id"]
