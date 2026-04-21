-- Run with: psql -v n8n_worker_password='YOUR_PASSWORD' -f 003_create_n8n_worker_user.sql

SET app.n8n_worker_password = :'n8n_worker_password';

DO $$
DECLARE
    pw TEXT := current_setting('app.n8n_worker_password');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_worker') THEN
        EXECUTE format('CREATE USER n8n_worker WITH PASSWORD %L', pw);
    ELSE
        EXECUTE format('ALTER USER n8n_worker WITH PASSWORD %L', pw);
    END IF;
END
$$;

GRANT CONNECT ON DATABASE fpcollector TO n8n_worker;
GRANT USAGE ON SCHEMA public TO n8n_worker;

GRANT SELECT ON raw_events TO n8n_worker;
GRANT UPDATE (processed_at, processing_error) ON raw_events TO n8n_worker;

GRANT INSERT ON clean_events TO n8n_worker;
GRANT INSERT ON leads TO n8n_worker;

GRANT USAGE, SELECT ON SEQUENCE clean_events_id_seq TO n8n_worker;
GRANT USAGE, SELECT ON SEQUENCE leads_id_seq TO n8n_worker;
