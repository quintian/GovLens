-- Step 7: hybrid retrieval and retrieval observability.
--
-- This migration adds full-text search support on chunks plus query/result
-- logs. The logs let the project show what was retrieved, how it was ranked,
-- and which source each result came from.

CREATE INDEX IF NOT EXISTS idx_document_chunks_text_search
    ON document_chunks USING gin (to_tsvector('english', chunk_text));

CREATE TABLE IF NOT EXISTS retrieval_queries (
    query_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,
    retrieval_mode TEXT NOT NULL CHECK (
        retrieval_mode IN ('vector', 'keyword', 'hybrid')
    ),
    embedding_model TEXT NOT NULL,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    result_count INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_retrieval_queries_time
    ON retrieval_queries (started_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_results (
    retrieval_result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL REFERENCES retrieval_queries(query_id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(source_id),
    rank INTEGER NOT NULL,
    vector_similarity DOUBLE PRECISION NOT NULL DEFAULT 0,
    keyword_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    hybrid_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (query_id, rank)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_results_query
    ON retrieval_results (query_id, rank);

CREATE INDEX IF NOT EXISTS idx_retrieval_results_chunk
    ON retrieval_results (chunk_id);
