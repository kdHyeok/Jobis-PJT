-- Prevent document vectors and query vectors from different embedding models
-- being compared in the same pgvector index.
CREATE TABLE IF NOT EXISTS rag_index_metadata (
    singleton         BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
    embed_provider    TEXT NOT NULL,
    embed_model       TEXT NOT NULL,
    embed_dimensions  INTEGER NOT NULL CHECK (embed_dimensions > 0),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Existing indexes were created by the original local BGE-M3 implementation.
-- Fresh databases remain without a profile until their first successful ingest.
INSERT INTO rag_index_metadata (
    singleton, embed_provider, embed_model, embed_dimensions
)
SELECT true, 'local', 'BAAI/bge-m3', 1024
WHERE EXISTS (SELECT 1 FROM chunks WHERE embedding IS NOT NULL)
ON CONFLICT (singleton) DO NOTHING;
