ALTER TABLE raw_events
    ADD COLUMN IF NOT EXISTS processed_at     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_error TEXT;

CREATE INDEX IF NOT EXISTS idx_raw_events_unprocessed
    ON raw_events (id)
    WHERE processed_at IS NULL AND processing_error IS NULL;
