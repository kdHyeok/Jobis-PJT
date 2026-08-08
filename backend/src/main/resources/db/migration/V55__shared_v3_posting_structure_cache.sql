CREATE TABLE ai_v3_posting_structure_cache (
    snapshot_hash varchar(80) PRIMARY KEY,
    contract_version varchar(80) NOT NULL,
    analysis_version varchar(160),
    structured_posting jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    invalidated_at timestamptz,
    invalid_reason text,
    CONSTRAINT ai_v3_structure_cache_document_check
        CHECK (jsonb_typeof(structured_posting) = 'object')
);

CREATE TABLE ai_v3_posting_structure_leases (
    snapshot_hash varchar(80) PRIMARY KEY,
    owner_analysis_job_id uuid NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    lease_until timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ai_v3_structure_cache_valid_idx
    ON ai_v3_posting_structure_cache (snapshot_hash)
    WHERE invalidated_at IS NULL;

CREATE TRIGGER ai_v3_posting_structure_cache_touch_updated_at
BEFORE UPDATE ON ai_v3_posting_structure_cache
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER ai_v3_posting_structure_leases_touch_updated_at
BEFORE UPDATE ON ai_v3_posting_structure_leases
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

GRANT SELECT, INSERT, UPDATE, DELETE ON
    ai_v3_posting_structure_cache,
    ai_v3_posting_structure_leases
TO jobiss_app;

REVOKE ALL ON
    ai_v3_posting_structure_cache,
    ai_v3_posting_structure_leases
FROM PUBLIC;
