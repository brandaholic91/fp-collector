import pytest
from pipeline import compute_source_medium


pytestmark = pytest.mark.no_db


def test_utm_params_take_priority():
    source, medium = compute_source_medium("Google", "CPC", None, "https://facebook.com/")
    assert source == "google"
    assert medium == "cpc"


def test_fbclid_fallback():
    source, medium = compute_source_medium(None, None, "abc123", None)
    assert source == "facebook"
    assert medium == "cpc"


def test_google_referrer():
    source, medium = compute_source_medium(None, None, None, "https://www.google.com/search?q=test")
    assert source == "google"
    assert medium == "organic"


def test_facebook_referrer():
    source, medium = compute_source_medium(None, None, None, "https://www.facebook.com/")
    assert source == "facebook"
    assert medium == "referral"


def test_instagram_referrer():
    source, medium = compute_source_medium(None, None, None, "https://instagram.com/p/abc")
    assert source == "facebook"
    assert medium == "referral"


def test_linkedin_referrer():
    source, medium = compute_source_medium(None, None, None, "https://linkedin.com/in/user")
    assert source == "linkedin"
    assert medium == "referral"


def test_twitter_referrer():
    source, medium = compute_source_medium(None, None, None, "https://twitter.com/user")
    assert source == "twitter"
    assert medium == "referral"


def test_x_com_referrer():
    source, medium = compute_source_medium(None, None, None, "https://x.com/user")
    assert source == "twitter"
    assert medium == "referral"


def test_unknown_referrer():
    source, medium = compute_source_medium(None, None, None, "https://somesite.com/page")
    assert source == "somesite.com"
    assert medium == "referral"


def test_no_referrer_is_direct():
    source, medium = compute_source_medium(None, None, None, None)
    assert source == "direct"
    assert medium == "none"


def test_empty_referrer_is_direct():
    source, medium = compute_source_medium(None, None, None, "")
    assert source == "direct"
    assert medium == "none"


def test_utm_requires_both_source_and_medium():
    # utm_source alone without utm_medium falls through to referrer logic
    source, medium = compute_source_medium("google", None, None, "https://facebook.com/")
    assert source == "facebook"
    assert medium == "referral"


# ---------------------------------------------------------------------------
# Integration tests for process_event
# ---------------------------------------------------------------------------
import uuid
import json
from datetime import datetime, timezone
import pytest_asyncio
from pipeline import process_event


def _raw_event(**kwargs):
    defaults = {
        "id": 1,
        "event_id": uuid.uuid4(),
        "event_name": "page_view",
        "occurred_at": datetime.now(timezone.utc),
        "session_id": "sess-test",
        "anonymous_id": "anon-test",
        "page_url": "https://example.com/",
        "referrer": None,
        "utm_source": "google",
        "utm_medium": "cpc",
        "utm_campaign": "test_campaign",
        "utm_term": None,
        "utm_content": None,
        "fbclid": None,
        "payload": "{}",
    }
    defaults.update(kwargs)
    return defaults


@pytest.mark.asyncio
async def test_process_event_inserts_clean_event(db_pool):
    row = _raw_event()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, utm_campaign, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,true,$10::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["utm_campaign"], row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        clean = await conn.fetchrow("SELECT * FROM clean_events WHERE event_id=$1", row["event_id"])
        assert clean is not None
        assert clean["event_name"] == "page_view"
        assert clean["source_medium"] == "google / cpc"
        assert clean["utm_source"] == "google"

        raw = await conn.fetchrow("SELECT processed_at, processing_error FROM raw_events WHERE event_id=$1", row["event_id"])
        assert raw["processed_at"] is not None
        assert raw["processing_error"] is None


@pytest.mark.asyncio
async def test_process_event_creates_lead_for_form_submit(db_pool):
    row = _raw_event(event_name="form_submit", payload='{"email": "test@example.com"}')
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        lead = await conn.fetchrow("SELECT * FROM leads WHERE event_id=$1", row["event_id"])
        assert lead is not None
        assert lead["utm_source"] == "google"


@pytest.mark.asyncio
async def test_process_event_no_lead_for_page_view(db_pool):
    row = _raw_event(event_name="page_view")
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)

        lead = await conn.fetchrow("SELECT * FROM leads WHERE event_id=$1", row["event_id"])
        assert lead is None


@pytest.mark.asyncio
async def test_process_event_duplicate_is_idempotent(db_pool):
    row = _raw_event()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO raw_events (event_id, event_name, occurred_at, session_id,
               anonymous_id, page_url, utm_source, utm_medium, consent_analytics, payload)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,true,$9::jsonb)""",
            row["event_id"], row["event_name"], row["occurred_at"], row["session_id"],
            row["anonymous_id"], row["page_url"], row["utm_source"], row["utm_medium"],
            row["payload"],
        )
        db_row = await conn.fetchrow("SELECT * FROM raw_events WHERE event_id=$1", row["event_id"])
        await process_event(conn, db_row)
        # second call should not raise
        await process_event(conn, db_row)

        count = await conn.fetchval("SELECT COUNT(*) FROM clean_events WHERE event_id=$1", row["event_id"])
        assert count == 1
