-- Step 4: normalize extracted text into document records and store quality
-- rule results.

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
    UNIQUE (source_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (document_status);

CREATE INDEX IF NOT EXISTS idx_documents_agency_topic
    ON documents (agency, topic);

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
