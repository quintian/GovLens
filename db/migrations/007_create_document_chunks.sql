-- Step 5: split AI-ready documents into retrieval-sized chunks.
--
-- Chunks are the bridge between normalized documents and vector search. The
-- full extracted text remains in extracted_text, while document_chunks stores
-- smaller sections that can later receive embeddings.

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(source_id),
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    chunk_hash TEXT NOT NULL,
    chunk_method TEXT NOT NULL DEFAULT 'word_window',
    character_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    section_heading TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document
    ON document_chunks (document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_document_chunks_source
    ON document_chunks (source_id);

CREATE INDEX IF NOT EXISTS idx_document_chunks_hash
    ON document_chunks (chunk_hash);
