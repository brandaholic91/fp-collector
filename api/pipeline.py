import json
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


async def process_event(conn: asyncpg.Connection, row: asyncpg.Record) -> None:
    source, medium = compute_source_medium(
        row["utm_source"], row["utm_medium"], row["fbclid"], row["referrer"]
    )
    source_medium = f"{source} / {medium}"

    # Caller must not have an active transaction on conn — this opens its own.
    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO clean_events (
                raw_event_id, event_id, event_name, occurred_at, session_id,
                anonymous_id, page_url, referrer, utm_source, utm_medium,
                utm_campaign, source_medium, payload
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            ON CONFLICT (event_id) DO NOTHING
            """,
            row["id"], row["event_id"], row["event_name"], row["occurred_at"],
            row["session_id"], row["anonymous_id"], row["page_url"], row["referrer"],
            row["utm_source"] or None, row["utm_medium"] or None,
            row["utm_campaign"] or None, source_medium, row["payload"],
        )

        if row["event_name"] == "form_submit":
            await conn.execute(
                """
                INSERT INTO leads (
                    event_id, anonymous_id, occurred_at,
                    utm_source, utm_medium, utm_campaign, payload
                )
                SELECT $1,$2,$3,$4,$5,$6,$7
                WHERE NOT EXISTS (SELECT 1 FROM leads WHERE event_id = $1)
                """,
                row["event_id"], row["anonymous_id"], row["occurred_at"],
                row["utm_source"] or None, row["utm_medium"] or None,
                row["utm_campaign"] or None, row["payload"],
            )

        if row["event_name"] == "purchase":
            order = json.loads(row["payload"])
            await conn.execute(
                """
                INSERT INTO orders (
                    order_id, event_id, value, currency, customer_key, anonymous_id,
                    session_id, occurred_at, utm_source, utm_medium, utm_campaign,
                    source_medium
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (order_id) DO NOTHING
                """,
                order["order_id"], row["event_id"], order["value"], order["currency"],
                order["customer_key"], row["anonymous_id"], row["session_id"],
                row["occurred_at"], row["utm_source"] or None,
                row["utm_medium"] or None, row["utm_campaign"] or None, source_medium,
            )
            await conn.execute(
                """
                INSERT INTO identity_links (anonymous_id, customer_key, first_seen_at)
                VALUES ($1,$2,$3)
                ON CONFLICT (anonymous_id, customer_key) DO UPDATE
                SET first_seen_at = LEAST(identity_links.first_seen_at, EXCLUDED.first_seen_at)
                """,
                row["anonymous_id"], order["customer_key"], row["occurred_at"],
            )

        await conn.execute(
            "UPDATE raw_events SET processed_at = now() WHERE id = $1",
            row["id"],
        )
