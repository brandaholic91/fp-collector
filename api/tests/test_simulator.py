import pytest
from simulator import pick_source, build_journey, SOURCES, WEIGHTS


def test_pick_source_returns_valid_source():
    source = pick_source()
    assert isinstance(source, dict)
    assert "utm_source" in source
    assert "utm_medium" in source
    assert "utm_campaign" in source


def test_pick_source_weights_sum_to_100():
    assert sum(WEIGHTS) == 100


def test_pick_source_direct_has_null_utm():
    # Run many times to ensure direct (null UTM) appears
    sources = [pick_source() for _ in range(200)]
    direct = [s for s in sources if s["utm_source"] is None]
    assert len(direct) > 0


def test_build_journey_always_starts_with_page_view():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    journey = build_journey(source)
    assert len(journey) >= 1
    assert journey[0]["event_name"] == "page_view"


def test_build_journey_page_view_has_correct_fields():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "brand"}
    journey = build_journey(source)
    pv = journey[0]
    assert pv["utm_source"] == "google"
    assert pv["utm_medium"] == "cpc"
    assert pv["consent_analytics"] is True
    assert pv["event_id"] is not None
    assert pv["session_id"] is not None
    assert pv["anonymous_id"] is not None


def test_build_journey_no_form_submit_without_cta_click():
    source = {"utm_source": None, "utm_medium": None, "utm_campaign": None}
    for _ in range(50):
        journey = build_journey(source)
        names = [e["event_name"] for e in journey]
        if "form_submit" in names:
            assert "cta_click" in names


def test_build_journey_all_events_share_session_and_anon_id():
    source = {"utm_source": "facebook", "utm_medium": "social", "utm_campaign": "test"}
    for _ in range(20):
        journey = build_journey(source)
        if len(journey) > 1:
            session_ids = {e["session_id"] for e in journey}
            anon_ids = {e["anonymous_id"] for e in journey}
            assert len(session_ids) == 1
            assert len(anon_ids) == 1
            break


def test_build_journey_form_submit_has_email_payload():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    found_form_submit = False
    for _ in range(100):
        journey = build_journey(source)
        for event in journey:
            if event["event_name"] == "form_submit":
                assert "email" in event["payload"]
                assert "@example.com" in event["payload"]["email"]
                found_form_submit = True
                break
        if found_form_submit:
            break


def test_build_journey_event_ids_are_unique():
    source = {"utm_source": "google", "utm_medium": "cpc", "utm_campaign": "test"}
    for _ in range(20):
        journey = build_journey(source)
        if len(journey) > 1:
            ids = [e["event_id"] for e in journey]
            assert len(ids) == len(set(ids))
            break
