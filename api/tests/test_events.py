import pytest

@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_db_pool_is_available(client):
    from main import app
    assert app.state.db_pool is not None


from models import EventRequest
import uuid
from datetime import datetime, timezone


def test_event_model_valid():
    data = {
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_abc",
        "anonymous_id": "anon_xyz",
        "page_url": "https://example.com",
        "consent_analytics": True,
        "payload": {},
    }
    event = EventRequest(**data)
    assert event.event_name == "page_view"


def test_event_model_rejects_invalid_event_name():
    from pydantic import ValidationError
    data = {
        "event_id": str(uuid.uuid4()),
        "event_name": "not_a_real_event",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_abc",
        "anonymous_id": "anon_xyz",
        "page_url": "https://example.com",
        "consent_analytics": True,
        "payload": {},
    }
    with pytest.raises(ValidationError):
        EventRequest(**data)


def make_event(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess_test",
        "anonymous_id": "anon_test",
        "page_url": "https://example.com/",
        "consent_analytics": True,
        "payload": {},
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ingest_valid_event(client):
    response = await client.post("/v1/events", json=make_event())
    assert response.status_code == 202
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ingest_duplicate_event(client):
    event = make_event()
    await client.post("/v1/events", json=event)
    response = await client.post("/v1/events", json=event)
    assert response.status_code == 202
    assert response.json() == {"status": "duplicate"}


@pytest.mark.asyncio
async def test_ingest_blocks_when_consent_false(client):
    response = await client.post("/v1/events", json=make_event(consent_analytics=False))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ingest_rejects_missing_required_field(client):
    event = make_event()
    del event["event_name"]
    response = await client.post("/v1/events", json=event)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_invalid_event_name(client):
    response = await client.post("/v1/events", json=make_event(event_name="bad_event"))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_rate_limit_applied(client):
    event_base = make_event()
    for i in range(100):
        event = {**event_base, "event_id": str(uuid.uuid4())}
        r = await client.post("/v1/events", json=event)
        assert r.status_code == 202

    event = {**event_base, "event_id": str(uuid.uuid4())}
    r = await client.post("/v1/events", json=event)
    assert r.status_code == 429
