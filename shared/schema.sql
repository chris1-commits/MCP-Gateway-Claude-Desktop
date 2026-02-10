-- Opulent Horizons MCP Gateway — PostgreSQL Schema
-- Run once against your target database before enabling Postgres mode.
--
-- Usage:
--   psql -h $PGHOST -U $PGUSER -d $PGDATABASE -f shared/schema.sql

BEGIN;

-- Lead context: stores full ingestion payload for each lead event
CREATE TABLE IF NOT EXISTS lead_context (
    id              UUID PRIMARY KEY,
    ohid            UUID NOT NULL,
    source_system   VARCHAR(50) NOT NULL,
    source_lead_id  VARCHAR(255),
    channel         VARCHAR(50),
    payload         JSONB NOT NULL,
    consent         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Workflow events: CloudTalk calls, Notion events, lead-ingested events
CREATE TABLE IF NOT EXISTS workflow_event (
    id              UUID PRIMARY KEY,
    ohid            UUID,
    event_type      VARCHAR(100) NOT NULL,
    payload         JSONB NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_system   VARCHAR(50) NOT NULL
);

-- Indexes for OHID lookup by email/phone (used by find_ohid_by_contact)
CREATE INDEX IF NOT EXISTS idx_lead_context_ohid
    ON lead_context (ohid);

CREATE INDEX IF NOT EXISTS idx_lead_context_email
    ON lead_context ((payload -> 'person' ->> 'email'))
    WHERE payload -> 'person' ->> 'email' IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lead_context_phone
    ON lead_context ((payload -> 'person' ->> 'phone'))
    WHERE payload -> 'person' ->> 'phone' IS NOT NULL;

-- Index for workflow event queries by OHID and type
CREATE INDEX IF NOT EXISTS idx_workflow_event_ohid
    ON workflow_event (ohid)
    WHERE ohid IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_workflow_event_type
    ON workflow_event (event_type);

COMMIT;
