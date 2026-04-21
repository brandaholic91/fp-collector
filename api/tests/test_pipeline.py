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
