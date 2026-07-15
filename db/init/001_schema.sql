-- GovLens database schema, Step 1.
--
-- The goal of this first schema is not to store all document text yet.
-- The goal is to create a governed source registry:
--   1. which public sources are allowed in the pipeline;
--   2. how each source should be fetched;
--   3. what happened the last time ingestion tried to fetch it.
--
-- Later steps will add raw documents, extracted text, chunks, embeddings,
-- retrieval logs, and answer lineage.

-- pgcrypto gives PostgreSQL the gen_random_uuid() function.
-- We use UUID primary keys so records are globally unique and easy to link
-- across ingestion, documents, chunks, embeddings, and lineage tables later.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- vector is provided by pgvector.
-- We enable it now because this project will later store embedding vectors
-- in PostgreSQL. This first schema does not create an embedding table yet.
CREATE EXTENSION IF NOT EXISTS vector;

-- sources is the canonical registry of public sources GovLens is allowed to
-- ingest. The ingestion code should read URLs from this table instead of
-- hardcoding URLs in Python scripts.
CREATE TABLE IF NOT EXISTS sources (
    -- Stable internal ID for this source.
    source_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Human-readable label shown in dashboards/logs.
    source_name TEXT NOT NULL,

    -- Canonical public URL. Unique prevents the same source from being
    -- registered twice.
    source_url TEXT NOT NULL UNIQUE,

    -- Describes how the source content is shaped. This helps later ingestion
    -- choose the right parser: PDF extraction, HTML extraction, API call, etc.
    source_type TEXT NOT NULL CHECK (
        source_type IN ('html', 'pdf', 'api', 'csv', 'rss', 'other')
    ),

    -- Agency or publisher. Useful for filtering, retrieval, audit, and
    -- dashboards.
    agency TEXT NOT NULL,

    -- Broad collection/domain. Example: federal_ai_policy.
    domain TEXT NOT NULL,

    -- More specific topic. Example: AI governance or AI risk management.
    topic TEXT NOT NULL,

    -- Tells ingestion how this source should be fetched.
    -- http_get: download a URL.
    -- api_query: call an API endpoint.
    -- manual_seed: source is curated or manually loaded.
    fetch_method TEXT NOT NULL DEFAULT 'http_get' CHECK (
        fetch_method IN ('http_get', 'api_query', 'manual_seed')
    ),

    -- How often the source should be checked for changes.
    refresh_policy TEXT NOT NULL DEFAULT 'weekly' CHECK (
        refresh_policy IN ('daily', 'weekly', 'monthly', 'manual')
    ),

    -- Lower number means higher priority. Ingestion can use this to fetch
    -- important sources first.
    priority INTEGER NOT NULL DEFAULT 100,

    -- Soft-disable switch. We keep the row for history but stop fetching it.
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Hash of the latest fetched content. If the hash changes, the source
    -- changed and downstream extraction/chunking/embedding should rerun.
    current_hash TEXT,

    -- Summary fields from the most recent fetch attempt.
    last_fetch_at TIMESTAMPTZ,
    last_status TEXT NOT NULL DEFAULT 'not_started' CHECK (
        last_status IN ('not_started', 'success', 'unchanged', 'failed', 'quarantined', 'disabled')
    ),
    last_http_status INTEGER,
    last_error TEXT,

    -- Free-form analyst/developer notes.
    notes TEXT,

    -- Basic audit fields.
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes make common filters faster.
CREATE INDEX IF NOT EXISTS idx_sources_agency ON sources (agency);
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources (domain);
CREATE INDEX IF NOT EXISTS idx_sources_topic ON sources (topic);
CREATE INDEX IF NOT EXISTS idx_sources_active_priority ON sources (is_active, priority);

-- ingestion_runs tracks one execution of the ingestion process.
-- This gives a dashboard-friendly summary: when a run started, whether it
-- succeeded, and how many sources changed or failed.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'success', 'failed')
    ),
    source_count INTEGER NOT NULL DEFAULT 0,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

-- source_fetch_events is the detailed audit trail for each source fetch.
-- One ingestion run can fetch many sources, and each source can have many
-- fetch events over time.
CREATE TABLE IF NOT EXISTS source_fetch_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Optional link to the ingestion run that produced this event.
    run_id UUID REFERENCES ingestion_runs(run_id),

    -- Which registered source was fetched.
    source_id UUID NOT NULL REFERENCES sources(source_id),

    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- success: fetched and accepted.
    -- unchanged: fetched but content hash matched previous version.
    -- failed: fetch failed.
    -- quarantined: fetched, but data quality checks rejected it.
    status TEXT NOT NULL CHECK (
        status IN ('success', 'failed', 'unchanged', 'quarantined')
    ),

    -- HTTP response code when available, such as 200 or 404.
    http_status INTEGER,

    -- Hash of fetched content for change detection.
    content_hash TEXT,

    -- Where the raw object was stored. This may be a local path now and an
    -- S3/MinIO object key later.
    object_path TEXT,

    -- Error detail for failed/quarantined events.
    error_message TEXT
);

-- Supports fast "show latest fetch events for this source" queries.
CREATE INDEX IF NOT EXISTS idx_source_fetch_events_source_time
    ON source_fetch_events (source_id, fetched_at DESC);

-- extracted_text stores readable text produced from raw fetched objects.
-- This table is still pre-embedding: it records full extracted text and
-- quality signals before later chunking.
CREATE TABLE IF NOT EXISTS extracted_text (
    extracted_text_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Link back to the original registered source.
    source_id UUID NOT NULL REFERENCES sources(source_id),

    -- Link back to the exact fetch event/raw object that produced this text.
    event_id UUID NOT NULL REFERENCES source_fetch_events(event_id),

    -- Where the raw file came from on disk/object storage.
    object_path TEXT NOT NULL,

    -- html_text, pdf_text, or another extractor name later.
    extraction_method TEXT NOT NULL,

    -- success or failed. Failed rows keep error_message for audit/debugging.
    extraction_status TEXT NOT NULL CHECK (
        extraction_status IN ('success', 'failed', 'quarantined')
    ),

    -- The extracted readable text. Later this will be chunked.
    extracted_text TEXT,

    -- Basic quality signals. These are not final quality gates yet, but they
    -- help us spot empty/poor extraction results early.
    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One extraction result per fetch event keeps reruns idempotent.
    UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_text_source
    ON extracted_text (source_id);

CREATE INDEX IF NOT EXISTS idx_extracted_text_status
    ON extracted_text (extraction_status);

-- documents is the normalized document inventory.
-- A source can produce multiple document versions over time when its content
-- hash changes. Each document row represents one source version that can move
-- toward chunking, embedding, and retrieval.
CREATE TABLE IF NOT EXISTS documents (
    document_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(source_id),
    event_id UUID NOT NULL REFERENCES source_fetch_events(event_id),
    extracted_text_id UUID NOT NULL REFERENCES extracted_text(extracted_text_id),
    title TEXT NOT NULL,
    source_url TEXT NOT NULL,
    agency TEXT NOT NULL,
    domain TEXT NOT NULL,
    topic TEXT NOT NULL,
    document_type TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version_number INTEGER NOT NULL DEFAULT 1,
    document_status TEXT NOT NULL CHECK (
        document_status IN ('candidate', 'ai_ready', 'quarantined')
    ),
    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One canonical document record per source/content version.
    UNIQUE (source_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (document_status);

CREATE INDEX IF NOT EXISTS idx_documents_agency_topic
    ON documents (agency, topic);

-- quality_results stores individual quality rule outcomes.
-- Keeping one row per rule gives us explainability: a document is not simply
-- "bad"; we can show exactly which rule failed.
CREATE TABLE IF NOT EXISTS quality_results (
    quality_result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    rule_name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    passed BOOLEAN NOT NULL,
    message TEXT NOT NULL,
    measured_value TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (document_id, rule_name)
);

CREATE INDEX IF NOT EXISTS idx_quality_results_document
    ON quality_results (document_id);

CREATE INDEX IF NOT EXISTS idx_quality_results_failed
    ON quality_results (passed, severity);
