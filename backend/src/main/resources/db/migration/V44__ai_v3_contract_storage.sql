CREATE TABLE ai_v3_source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    posting_id uuid,
    source_document_id varchar(160) NOT NULL,
    entry_point varchar(40) NOT NULL,
    input_type varchar(20) NOT NULL,
    extraction_revision integer NOT NULL,
    status varchar(40) NOT NULL,
    canonical_input_hash varchar(80) NOT NULL,
    content_hash varchar(80) NOT NULL,
    document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (source_document_id),
    UNIQUE (user_id, posting_id, extraction_revision),
    CONSTRAINT ai_v3_source_posting_owner_fk
        FOREIGN KEY (posting_id, user_id)
        REFERENCES job_postings(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_v3_source_entry_point_check
        CHECK (entry_point IN ('CHAT', 'POSTINGS_PAGE', 'INTERNAL')),
    CONSTRAINT ai_v3_source_input_type_check
        CHECK (input_type IN ('URL', 'IMAGE', 'TEXT')),
    CONSTRAINT ai_v3_source_revision_check
        CHECK (extraction_revision >= 1),
    CONSTRAINT ai_v3_source_document_check
        CHECK (jsonb_typeof(document) = 'object')
);

CREATE TABLE ai_v3_verified_posting_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id uuid NOT NULL,
    verified_snapshot_id varchar(160) NOT NULL,
    source_revision integer NOT NULL,
    previous_snapshot_id varchar(160),
    snapshot_hash varchar(80) NOT NULL,
    verified_by varchar(40) NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    UNIQUE (verified_snapshot_id),
    UNIQUE (source_id, source_revision, snapshot_hash),
    CONSTRAINT ai_v3_snapshot_source_owner_fk
        FOREIGN KEY (source_id, user_id)
        REFERENCES ai_v3_source_documents(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_v3_snapshot_verified_by_check
        CHECK (verified_by IN ('USER', 'OPERATOR', 'TRUSTED_DIRECT_SOURCE')),
    CONSTRAINT ai_v3_snapshot_revision_check
        CHECK (source_revision >= 1),
    CONSTRAINT ai_v3_snapshot_document_check
        CHECK (jsonb_typeof(snapshot) = 'object')
);

CREATE TABLE ai_v3_analysis_runs (
    analysis_job_id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id uuid NOT NULL,
    verified_snapshot_id uuid NOT NULL,
    run_revision integer NOT NULL DEFAULT 1,
    common_analysis_id varchar(160) NOT NULL,
    opportunity_id varchar(160) NOT NULL,
    contract_version varchar(80) NOT NULL,
    state varchar(60) NOT NULL DEFAULT 'RECEIVED',
    based_on_roadmap_version bigint NOT NULL DEFAULT 0,
    request_data jsonb,
    structured_posting jsonb,
    fit_result jsonb,
    normalization_result jsonb,
    roadmap_proposal jsonb,
    result_data jsonb,
    active_ambiguity jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (analysis_job_id, user_id),
    CONSTRAINT ai_v3_run_job_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_v3_run_source_owner_fk
        FOREIGN KEY (source_id, user_id)
        REFERENCES ai_v3_source_documents(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_v3_run_snapshot_owner_fk
        FOREIGN KEY (verified_snapshot_id, user_id)
        REFERENCES ai_v3_verified_posting_snapshots(id, user_id)
        ON DELETE RESTRICT,
    CONSTRAINT ai_v3_run_revision_check CHECK (run_revision >= 1),
    CONSTRAINT ai_v3_run_request_check
        CHECK (request_data IS NULL OR jsonb_typeof(request_data) = 'object'),
    CONSTRAINT ai_v3_run_result_check
        CHECK (result_data IS NULL OR jsonb_typeof(result_data) = 'object'),
    CONSTRAINT ai_v3_run_ambiguity_check
        CHECK (active_ambiguity IS NULL OR jsonb_typeof(active_ambiguity) = 'object')
);

CREATE TABLE ai_v3_roadmap_proposals (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    analysis_job_id uuid NOT NULL,
    proposal_id varchar(160) NOT NULL,
    based_on_roadmap_version bigint NOT NULL,
    proposed_roadmap_version bigint NOT NULL,
    status varchar(30) NOT NULL DEFAULT 'DRAFT',
    proposal jsonb NOT NULL,
    preview_snapshot jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz,
    cancelled_at timestamptz,
    UNIQUE (id, user_id),
    UNIQUE (proposal_id),
    UNIQUE (analysis_job_id),
    CONSTRAINT ai_v3_proposal_job_owner_fk
        FOREIGN KEY (analysis_job_id, user_id)
        REFERENCES analysis_jobs(id, user_id)
        ON DELETE CASCADE,
    CONSTRAINT ai_v3_proposal_status_check
        CHECK (status IN ('DRAFT', 'APPLIED', 'CANCELLED', 'SUPERSEDED')),
    CONSTRAINT ai_v3_proposal_version_check
        CHECK (proposed_roadmap_version = based_on_roadmap_version + 1),
    CONSTRAINT ai_v3_proposal_document_check
        CHECK (jsonb_typeof(proposal) = 'object'),
    CONSTRAINT ai_v3_proposal_preview_check
        CHECK (preview_snapshot IS NULL OR jsonb_typeof(preview_snapshot) = 'object')
);

CREATE INDEX ai_v3_sources_user_created_idx
    ON ai_v3_source_documents (user_id, created_at DESC);
CREATE INDEX ai_v3_snapshots_source_created_idx
    ON ai_v3_verified_posting_snapshots (source_id, created_at DESC);
CREATE INDEX ai_v3_runs_user_state_idx
    ON ai_v3_analysis_runs (user_id, state, created_at DESC);
CREATE INDEX ai_v3_proposals_user_status_idx
    ON ai_v3_roadmap_proposals (user_id, status, created_at DESC);

CREATE TRIGGER ai_v3_source_documents_touch_updated_at
BEFORE UPDATE ON ai_v3_source_documents
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER ai_v3_analysis_runs_touch_updated_at
BEFORE UPDATE ON ai_v3_analysis_runs
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER ai_v3_roadmap_proposals_touch_updated_at
BEFORE UPDATE ON ai_v3_roadmap_proposals
FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

ALTER TABLE ai_v3_source_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_source_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_verified_posting_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_verified_posting_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_analysis_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_roadmap_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_v3_roadmap_proposals FORCE ROW LEVEL SECURITY;

CREATE POLICY ai_v3_source_documents_owner_policy ON ai_v3_source_documents
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY ai_v3_snapshots_owner_policy ON ai_v3_verified_posting_snapshots
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY ai_v3_analysis_runs_owner_policy ON ai_v3_analysis_runs
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());
CREATE POLICY ai_v3_roadmap_proposals_owner_policy ON ai_v3_roadmap_proposals
    USING (user_id = app_current_user_id())
    WITH CHECK (user_id = app_current_user_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON
    ai_v3_source_documents,
    ai_v3_verified_posting_snapshots,
    ai_v3_analysis_runs,
    ai_v3_roadmap_proposals
TO jobiss_app;

REVOKE ALL ON
    ai_v3_source_documents,
    ai_v3_verified_posting_snapshots,
    ai_v3_analysis_runs,
    ai_v3_roadmap_proposals
FROM PUBLIC;
