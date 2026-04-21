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
    payload           JSONB       NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_raw_events_occurred_at ON raw_events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_raw_events_event_name  ON raw_events (event_name);
CREATE INDEX IF NOT EXISTS idx_raw_events_session_id  ON raw_events (session_id);

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
