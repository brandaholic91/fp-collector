CREATE TABLE IF NOT EXISTS raw_events (
    id                BIGSERIAL   PRIMARY KEY,
    event_id          UUID        NOT NULL UNIQUE,
    event_name        TEXT        NOT NULL,
    occurred_at       TIMESTAMPTZ NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id        TEXT        NOT NULL,
    anonymous_id      TEXT        NOT NULL,
    page_url          TEXT        NOT NULL,
    referrer          TEXT,
    utm_source        TEXT,
    utm_medium        TEXT,
    utm_campaign      TEXT,
    utm_term          TEXT,
    utm_content       TEXT,
    fbclid            TEXT,
    consent_analytics BOOLEAN     NOT NULL,
    payload           JSONB       NOT NULL DEFAULT '{}',
    processed_at      TIMESTAMPTZ,
    processing_error  TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_events_occurred_at ON raw_events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_event_name  ON raw_events (event_name);
CREATE INDEX IF NOT EXISTS idx_raw_events_session_id  ON raw_events (session_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed ON raw_events (id)
    WHERE processed_at IS NULL AND processing_error IS NULL;

CREATE TABLE IF NOT EXISTS clean_events (
    id            BIGSERIAL   PRIMARY KEY,
    raw_event_id  BIGINT      REFERENCES raw_events(id),
    event_id      UUID        NOT NULL UNIQUE,
    event_name    TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    session_id    TEXT        NOT NULL,
    anonymous_id  TEXT        NOT NULL,
    page_url      TEXT        NOT NULL,
    referrer      TEXT,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    source_medium TEXT,
    payload       JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS leads (
    id            BIGSERIAL   PRIMARY KEY,
    event_id      UUID        REFERENCES clean_events(event_id),
    anonymous_id  TEXT        NOT NULL,
    occurred_at   TIMESTAMPTZ NOT NULL,
    utm_source    TEXT,
    utm_medium    TEXT,
    utm_campaign  TEXT,
    payload       JSONB       NOT NULL DEFAULT '{}'
);

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
