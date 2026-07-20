-- Step 6: store vector embeddings for retrieval-ready chunks.
--
-- chunk_embeddings is separate from document_chunks so the same chunk can be
-- embedded again later with a different model or model version without losing
-- lineage to the original text.

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES document_chunks(chunk_id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES sources(source_id),
    embedding_model TEXT NOT NULL,
    embedding_dimension INTEGER NOT NULL,
    embedding vector(128) NOT NULL,
    chunk_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, embedding_model)
);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_chunk
    ON chunk_embeddings (chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_model
    ON chunk_embeddings (embedding_model);

CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_vector
    ON chunk_embeddings USING hnsw (embedding vector_cosine_ops);
