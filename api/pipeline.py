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


async def process_rows_batched(conn: asyncpg.Connection, rows: list) -> None:
    """Same result as process_event, for a whole batch in ONE transaction with
    set-based SQL. source_medium is still computed in Python (the rule lives
    in one place) and travels back to SQL paired with the row id.

    If anything raises, the transaction rolls back and the caller retries the
    rows one by one, so a single bad row cannot block the rest.
    """
    ids = [r["id"] for r in rows]
    source_mediums = [
        "%s / %s" % compute_source_medium(
            r["utm_source"], r["utm_medium"], r["fbclid"], r["referrer"]
        )
        for r in rows
    ]

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO clean_events (
                raw_event_id, event_id, event_name, occurred_at, session_id,
                anonymous_id, page_url, referrer, utm_source, utm_medium,
                utm_campaign, source_medium, payload
            )
            SELECT r.id, r.event_id, r.event_name, r.occurred_at, r.session_id,
                   r.anonymous_id, r.page_url, r.referrer,
                   NULLIF(r.utm_source, ''), NULLIF(r.utm_medium, ''),
                   NULLIF(r.utm_campaign, ''), t.source_medium, r.payload
            FROM raw_events r
            JOIN unnest($1::bigint[], $2::text[]) AS t(id, source_medium) ON t.id = r.id
            ORDER BY r.id
            ON CONFLICT (event_id) DO NOTHING
            """,
            ids, source_mediums,
        )
        await conn.execute(
            """
            INSERT INTO leads (
                event_id, anonymous_id, occurred_at,
                utm_source, utm_medium, utm_campaign, payload
            )
            SELECT r.event_id, r.anonymous_id, r.occurred_at,
                   NULLIF(r.utm_source, ''), NULLIF(r.utm_medium, ''),
                   NULLIF(r.utm_campaign, ''), r.payload
            FROM raw_events r
            WHERE r.id = ANY($1::bigint[]) AND r.event_name = 'form_submit'
              AND NOT EXISTS (SELECT 1 FROM leads l WHERE l.event_id = r.event_id)
            ORDER BY r.id
            """,
            ids,
        )
        await conn.execute(
            """
            INSERT INTO orders (
                order_id, event_id, value, currency, customer_key, anonymous_id,
                session_id, occurred_at, utm_source, utm_medium, utm_campaign,
                source_medium
            )
            SELECT r.payload->>'order_id', r.event_id, (r.payload->>'value')::numeric,
                   r.payload->>'currency', r.payload->>'customer_key', r.anonymous_id,
                   r.session_id, r.occurred_at,
                   NULLIF(r.utm_source, ''), NULLIF(r.utm_medium, ''),
                   NULLIF(r.utm_campaign, ''), t.source_medium
            FROM raw_events r
            JOIN unnest($1::bigint[], $2::text[]) AS t(id, source_medium) ON t.id = r.id
            WHERE r.event_name = 'purchase'
            ORDER BY r.id
            ON CONFLICT (order_id) DO NOTHING
            """,
            ids, source_mediums,
        )
        # GROUP BY: if the same pair appears twice in a batch, ON CONFLICT DO
        # UPDATE would touch one row twice and Postgres would raise.
        await conn.execute(
            """
            INSERT INTO identity_links (anonymous_id, customer_key, first_seen_at)
            SELECT r.anonymous_id, r.payload->>'customer_key', MIN(r.occurred_at)
            FROM raw_events r
            WHERE r.id = ANY($1::bigint[]) AND r.event_name = 'purchase'
            GROUP BY 1, 2
            ON CONFLICT (anonymous_id, customer_key) DO UPDATE
            SET first_seen_at = LEAST(identity_links.first_seen_at, EXCLUDED.first_seen_at)
            """,
            ids,
        )
        await conn.execute(
            "UPDATE raw_events SET processed_at = now() WHERE id = ANY($1::bigint[])",
            ids,
        )


# Events the simulator made carry payload.simulated = true; they are not
# visitor data, so retention leaves them alone.
_EXPIRED = """
    SELECT event_id FROM raw_events
    WHERE received_at < now() - make_interval(days => $1)
      AND NOT (payload @> '{"simulated": true}')
"""


async def purge_expired(conn: asyncpg.Connection, days: int) -> int:
    """Delete visitor events received more than `days` days ago, from every table.

    Returns the number of raw_events rows deleted.
    """
    async with conn.transaction():
        # Children first: leads and orders point at clean_events, which points at raw_events.
        for table in ("leads", "orders", "clean_events"):
            # Production runs without the e-commerce migration, so orders may not exist.
            if await conn.fetchval("SELECT to_regclass($1)", table) is None:
                continue
            await conn.execute(f"DELETE FROM {table} WHERE event_id IN ({_EXPIRED})", days)
        status = await conn.execute(f"DELETE FROM raw_events WHERE event_id IN ({_EXPIRED})", days)
    return int(status.split()[-1])
