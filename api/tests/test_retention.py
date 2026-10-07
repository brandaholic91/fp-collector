from tests.helpers import make_event, run_worker
from pipeline import purge_expired


async def _post(client, **overrides):
    event = make_event(**overrides)
    resp = await client.post("/v1/events", json=event)
    assert resp.status_code in (200, 201, 202), resp.text
    return event["event_id"]


async def _age(conn, event_id, days):
    await conn.execute(
        "UPDATE raw_events SET received_at = now() - make_interval(days => $2) WHERE event_id = $1::uuid",
        event_id, days,
    )


async def _counts(conn, event_id):
    """Rows this event has in raw_events, clean_events and leads."""
    return tuple([
        await conn.fetchval(f"SELECT count(*) FROM {t} WHERE event_id = $1::uuid", event_id)
        for t in ("raw_events", "clean_events", "leads")
    ])


async def test_old_visitor_event_is_deleted_from_every_table(client, db_pool):
    old = await _post(client, event_name="form_submit", payload={"email": "a@example.com"})
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        await _age(conn, old, 91)
        assert await _counts(conn, old) == (1, 1, 1)
        await purge_expired(conn, 90)
        assert await _counts(conn, old) == (0, 0, 0)


async def test_recent_visitor_event_is_kept(client, db_pool):
    recent = await _post(client, event_name="form_submit", payload={"email": "a@example.com"})
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        await _age(conn, recent, 89)
        await purge_expired(conn, 90)
        assert await _counts(conn, recent) == (1, 1, 1)


async def test_old_simulated_event_is_kept(client, db_pool):
    simulated = await _post(
        client, event_name="form_submit", payload={"email": "a@example.com", "simulated": True}
    )
    await run_worker(db_pool)
    async with db_pool.acquire() as conn:
        await _age(conn, simulated, 400)
        await purge_expired(conn, 90)
        assert await _counts(conn, simulated) == (1, 1, 1)


async def test_old_unprocessed_event_is_deleted(client, db_pool):
    old = await _post(client)
    async with db_pool.acquire() as conn:
        await _age(conn, old, 91)
        await purge_expired(conn, 90)
        assert await _counts(conn, old) == (0, 0, 0)
