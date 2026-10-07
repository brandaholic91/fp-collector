-- E-commerce (ECOMMERCE_ENABLED). Only the world instance uses these.
CREATE TABLE IF NOT EXISTS orders (
    id            BIGSERIAL   PRIMARY KEY,
    order_id      TEXT        NOT NULL UNIQUE,
    event_id      UUID        REFERENCES clean_events(event_id),
    value         NUMERIC     NOT NULL,
    currency      TEXT        NOT NULL,
    customer_key  TEXT        NOT NULL,
    anonymous_id  TEXT        NOT NULL,
    session_id    TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    source_medium TEXT
);

CREATE TABLE IF NOT EXISTS identity_links (
    id            BIGSERIAL   PRIMARY KEY,
    anonymous_id  TEXT        NOT NULL,
    customer_key  TEXT        NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    UNIQUE (anonymous_id, customer_key)
);


-- person_id is resolved at read time: the customer_key if the device has a
-- link, otherwise the anonymous_id itself. With several links the earliest wins.
-- Read-time resolution means a purchase claims the device's EARLIER events too.
CREATE OR REPLACE VIEW resolved_events AS
SELECT ce.*, COALESCE(l.customer_key, ce.anonymous_id) AS person_id
FROM clean_events ce
LEFT JOIN (
    SELECT DISTINCT ON (anonymous_id) anonymous_id, customer_key
    FROM identity_links
    ORDER BY anonymous_id, first_seen_at, customer_key
) l ON l.anonymous_id = ce.anonymous_id;
