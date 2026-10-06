import uuid
from datetime import datetime, timezone

T0 = datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc)


def make_event(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "event_name": "page_view",
        "occurred_at": T0.isoformat(),
        "session_id": "sess_test",
        "anonymous_id": "anon_test",
        "page_url": "https://bolt.example/",
        "consent_analytics": True,
        "payload": {},
    }
    base.update(overrides)
    return base


def make_purchase(order_id="o-1", customer_key="cust-1", value=12500, **overrides):
    return make_event(
        event_name="purchase",
        payload={"order_id": order_id, "value": value, "currency": "HUF",
                 "customer_key": customer_key},
        **overrides,
    )


async def run_worker(pool):
    from worker import process_batch
    while await process_batch(pool):
        pass
