import re
import asyncpg


def _hostname(url: str | None) -> str | None:
    if not url:
        return None
    m = re.match(r"^https?://([^/:?#]+)", url, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).lower().removeprefix("www.")


def compute_source_medium(
    utm_source: str | None,
    utm_medium: str | None,
    fbclid: str | None,
    referrer: str | None,
) -> tuple[str, str]:
    if utm_source and utm_medium:
        return utm_source.lower(), utm_medium.lower()
    if fbclid:
        return "facebook", "cpc"
    host = _hostname(referrer)
    if host:
        if "google." in host:
            return "google", "organic"
        if "facebook." in host or "instagram." in host:
            return "facebook", "referral"
        if "linkedin." in host:
            return "linkedin", "referral"
        if "twitter." in host or "t.co" == host or "x.com" == host:
            return "twitter", "referral"
        return host, "referral"
    return "direct", "none"
