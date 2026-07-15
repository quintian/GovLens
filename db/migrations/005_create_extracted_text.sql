-- Step 3: store readable text extracted from raw fetched objects.

CREATE TABLE IF NOT EXISTS extracted_text (
    extracted_text_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(source_id),
    event_id UUID NOT NULL REFERENCES source_fetch_events(event_id),
    object_path TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    extraction_status TEXT NOT NULL CHECK (
        extraction_status IN ('success', 'failed', 'quarantined')
    ),
    extracted_text TEXT,
    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_extracted_text_source
    ON extracted_text (source_id);

CREATE INDEX IF NOT EXISTS idx_extracted_text_status
    ON extracted_text (extraction_status);
